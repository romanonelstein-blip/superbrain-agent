export class MockProvider {
    name = "mock";
    model = "mock-model";
    async runAgent(agent, task) {
        return {
            text: `[${agent}] analysis for: ${task}`,
            provider: this.name,
            model: this.model,
            latencyMs: 0
        };
    }
}
