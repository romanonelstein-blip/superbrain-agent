import { describe, expect, it } from "./testkit.js";
import { ModelProvider } from "../src/provider.js";
import { AgentName, ProviderExecution } from "../src/types.js";
import { ProviderRouter } from "../src/providers/router.js";

function provider(
  name: "openai" | "anthropic" | "gemini",
  shouldFail: boolean
): ModelProvider {
  return {
    name,
    model: `${name}-test`,
    async runAgent(agent: AgentName, task: string): Promise<ProviderExecution> {
      if (shouldFail) throw new Error(`${name} unavailable`);
      return {
        text: `${name}:${agent}:${task}`,
        provider: name,
        model: `${name}-test`,
        latencyMs: 5
      };
    }
  };
}

describe("ProviderRouter", () => {
  it("selects the first configured provider without unnecessary fallback", async () => {
    const router = new ProviderRouter(
      [provider("openai", false), provider("anthropic", false)],
      { strategy: ["openai", "anthropic"] }
    );

    const result = await router.runAgent("strategy", "test task");

    expect(result.provider).toBe("openai");
    expect(result.attempts).toBe(1);
  });

  it("fails over to the next provider without losing the run", async () => {
    const router = new ProviderRouter(
      [provider("openai", true), provider("anthropic", false)],
      { strategy: ["openai", "anthropic"] }
    );

    const result = await router.runAgent("strategy", "test task");

    expect(result.provider).toBe("anthropic");
    expect(result.attempts).toBe(2);
  });
});
