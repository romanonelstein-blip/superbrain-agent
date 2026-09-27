import { describe, expect, it } from "./testkit.js";
import { MockProvider } from "../src/provider.js";
import { SuperbrainOrchestrator } from "../src/orchestrator.js";

describe("SuperbrainOrchestrator compatibility wrapper", () => {
  it("delegates to the canonical Nexus provider mission path", async () => {
    const orchestrator = new SuperbrainOrchestrator(new MockProvider());

    const result = await orchestrator.run({
      task: "Research and build a business strategy for a new AI architecture"
    });

    expect(result.evidence.length).toBeGreaterThan(0);
    expect(result.evidence.every(item => item.provider === "mock")).toBe(true);
    expect(result.evidence.every(item => item.verified === false)).toBe(true);
  });
});
