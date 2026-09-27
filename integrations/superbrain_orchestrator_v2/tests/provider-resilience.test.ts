import { describe, expect, it } from "./testkit.js";
import { ModelProvider } from "../src/provider.js";
import { AgentName, ProviderExecution } from "../src/types.js";
import { ProviderRouter } from "../src/providers/router.js";
import { ProviderHttpError, classifyProviderFailure, sanitizeProviderError } from "../src/providers/index.js";

function scriptedProvider(
  name: "openai" | "anthropic" | "gemini",
  script: Array<"ok" | "server" | "auth" | "timeout">,
  model = `${name}-test`
): ModelProvider {
  let index = 0;
  return {
    name,
    model,
    async runAgent(agent: AgentName, task: string): Promise<ProviderExecution> {
      const action = script[Math.min(index++, script.length - 1)] ?? "ok";
      if (action === "server") throw new ProviderHttpError(name, 503, "temporary outage");
      if (action === "auth") throw new ProviderHttpError(name, 401, "invalid key");
      if (action === "timeout") {
        const error = new Error("request timeout");
        error.name = "AbortError";
        throw error;
      }
      return {
        text: `${name}:${agent}:${task}`,
        provider: name,
        model,
        latencyMs: 5
      };
    }
  };
}

describe("provider resilience", () => {
  it("retries temporary failures before failing over", async () => {
    const router = new ProviderRouter(
      [scriptedProvider("openai", ["server", "ok"]), scriptedProvider("anthropic", ["ok"])],
      { strategy: ["openai", "anthropic"] },
      { resilience: { maxAttemptsPerProvider: 2, retryBaseDelayMs: 0 } }
    );

    const result = await router.runAgent("strategy", "test");
    expect(result.provider).toBe("openai");
    expect(result.attempts).toBe(2);
    expect(result.resilience?.failures[0]?.kind).toBe("server");
  });

  it("does not retry authentication errors and fails over immediately", async () => {
    const router = new ProviderRouter(
      [scriptedProvider("openai", ["auth", "ok"]), scriptedProvider("anthropic", ["ok"])],
      { strategy: ["openai", "anthropic"] },
      { resilience: { maxAttemptsPerProvider: 3, retryBaseDelayMs: 0 } }
    );

    const result = await router.runAgent("strategy", "test");
    expect(result.provider).toBe("anthropic");
    expect(result.attempts).toBe(2);
    expect(result.resilience?.failures[0]).toMatchObject({ provider: "openai", kind: "auth", retryable: false });
  });

  it("enforces provider and model allowlists", async () => {
    const router = new ProviderRouter(
      [scriptedProvider("openai", ["ok"], "openai-test"), scriptedProvider("anthropic", ["ok"], "anthropic-test")],
      { strategy: ["openai", "anthropic"] },
      { resilience: { allowedProviders: ["openai"], allowedModels: { openai: ["other-model"] } } }
    );

    await expect(router.runAgent("strategy", "test")).rejects.toThrow(/model_not_allowed|provider_not_allowed/);
  });

  it("opens the circuit after repeated failures and skips the unhealthy provider", async () => {
    let now = 1000;
    const router = new ProviderRouter(
      [scriptedProvider("openai", ["server", "server", "server"]), scriptedProvider("anthropic", ["ok", "ok"])],
      { strategy: ["openai", "anthropic"] },
      {
        now: () => now,
        resilience: {
          maxAttemptsPerProvider: 1,
          circuitBreakerFailureThreshold: 2,
          circuitBreakerCooldownMs: 10_000,
          retryBaseDelayMs: 0
        }
      }
    );

    expect((await router.runAgent("strategy", "one")).provider).toBe("anthropic");
    expect((await router.runAgent("strategy", "two")).provider).toBe("anthropic");
    const third = await router.runAgent("strategy", "three");
    expect(third.provider).toBe("anthropic");
    expect(third.resilience?.failures.some(f => f.kind === "circuit_open")).toBe(true);
    now += 20_000;
  });

  it("enforces local rate limits", async () => {
    const router = new ProviderRouter(
      [scriptedProvider("openai", ["server", "server"]), scriptedProvider("anthropic", ["ok"])],
      { strategy: ["openai", "anthropic"] },
      {
        now: () => 1000,
        resilience: { maxAttemptsPerProvider: 2, rateLimitMaxAttempts: 1, retryBaseDelayMs: 0 }
      }
    );

    const result = await router.runAgent("strategy", "test");
    expect(result.provider).toBe("anthropic");
    expect(result.resilience?.failures.some(f => f.kind === "rate_limit")).toBe(true);
  });

  it("enforces cost budgets", async () => {
    const router = new ProviderRouter(
      [scriptedProvider("openai", ["server", "server"]), scriptedProvider("anthropic", ["ok"])],
      { strategy: ["openai", "anthropic"] },
      {
        resilience: {
          maxAttemptsPerProvider: 2,
          maxCostUnits: 1,
          costUnitsPerAttempt: { openai: 1, anthropic: 1 },
          retryBaseDelayMs: 0
        }
      }
    );

    await expect(router.runAgent("strategy", "test")).rejects.toThrow(/budget_exhausted/);
  });

  it("classifies retryable and terminal HTTP failures", () => {
    expect(classifyProviderFailure(new ProviderHttpError("openai", 429, "busy"))).toMatchObject({ kind: "rate_limit", retryable: true });
    expect(classifyProviderFailure(new ProviderHttpError("openai", 400, "bad"))).toMatchObject({ kind: "bad_request", retryable: false });
  });

  it("redacts common credential patterns from errors", () => {
    const sanitized = sanitizeProviderError(new Error("Bearer abc.def.ghi api_key=supersecret sk-abcdef"));
    expect(sanitized).not.toContain("abc.def.ghi");
    expect(sanitized).not.toContain("supersecret");
    expect(sanitized).not.toContain("sk-abcdef");
  });
});
