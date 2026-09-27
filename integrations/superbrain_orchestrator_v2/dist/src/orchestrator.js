import { runNexusProviderMission } from "./nexus-bridge.js";
/**
 * @deprecated Use runNexusProviderMission. This wrapper exists only for deep-import
 * compatibility and delegates to the single canonical provider execution path.
 */
export class SuperbrainOrchestrator {
    provider;
    constructor(provider) {
        this.provider = provider;
    }
    async run(request) {
        return runNexusProviderMission(this.provider, request);
    }
}
