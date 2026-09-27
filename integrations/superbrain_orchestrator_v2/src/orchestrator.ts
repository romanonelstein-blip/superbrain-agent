import { runNexusProviderMission, NexusProviderBatch } from "./nexus-bridge.js";
import { ModelProvider } from "./provider.js";
import { OrchestrationRequest } from "./types.js";

/**
 * @deprecated Use runNexusProviderMission. This wrapper exists only for deep-import
 * compatibility and delegates to the single canonical provider execution path.
 */
export class SuperbrainOrchestrator {
  constructor(private provider: ModelProvider) {}

  async run(request: OrchestrationRequest): Promise<NexusProviderBatch> {
    return runNexusProviderMission(this.provider, request);
  }
}
