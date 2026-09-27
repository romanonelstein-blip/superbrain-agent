import { describe, expect, it } from "./testkit.js";
import * as publicApi from "../src/index.js";
describe("public API", () => {
    it("exports the Nexus provider bridge but not the legacy final-decision orchestrator", () => {
        expect(publicApi).toHaveProperty("runNexusProviderMission");
        expect(publicApi).not.toHaveProperty("SuperbrainOrchestrator");
    });
});
