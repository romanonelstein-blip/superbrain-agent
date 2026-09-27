import { describe, expect, it } from "./testkit.js";
import { ModelProvider } from "../src/provider.js";
import { runNexusProviderMission } from "../src/nexus-bridge.js";

describe("Nexus provider bridge", () => {
  it("preserves provider provenance without self-verifying model output", async () => {
    const provider: ModelProvider = {
      name: "openai",
      model: "test-model",
      async runAgent(agent) {
        return {
          text: `claim from ${agent}`,
          provider: "openai",
          model: "test-model",
          requestId: `req-${agent}`,
          latencyMs: 7,
          attempts: 2
        };
      }
    };

    const result = await runNexusProviderMission(provider, {
      task: "Research a launch strategy",
      preferredAgents: ["research", "strategy"]
    });

    expect(result.evidence).toHaveLength(2);
    expect(result.evidence[0]).toMatchObject({
      provider: "openai",
      model: "test-model",
      verified: false,
      latency_ms: 7,
      attempts: 2
    });
    expect(result.evidence.map(item => item.request_id)).toEqual([
      "req-research",
      "req-strategy"
    ]);
  });

  it("propagates provider failure instead of silently synthesizing", async () => {
    const provider: ModelProvider = {
      name: "openai",
      model: "test-model",
      async runAgent() {
        throw new Error("provider offline");
      }
    };

    await expect(runNexusProviderMission(provider, { task: "Research launch" }))
      .rejects.toThrow("provider offline");
  });
});
