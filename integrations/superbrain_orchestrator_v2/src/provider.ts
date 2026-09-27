import { AgentName, ProviderExecution, ProviderName } from "./types.js";

export interface ModelProvider {
  readonly name: ProviderName;
  readonly model: string;
  runAgent(
    agent: AgentName,
    task: string,
    context?: Record<string, unknown>
  ): Promise<ProviderExecution>;
}

export class MockProvider implements ModelProvider {
  readonly name = "mock" as const;
  readonly model = "mock-model";

  async runAgent(agent: AgentName, task: string): Promise<ProviderExecution> {
    return {
      text: `[${agent}] analysis for: ${task}`,
      provider: this.name,
      model: this.model,
      latencyMs: 0
    };
  }
}
