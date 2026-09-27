import { routeAgents } from "./router.js";
export async function runNexusProviderMission(provider, request) {
    const agents = routeAgents(request).filter((agent) => !["critic", "verifier"].includes(agent));
    const evidence = await Promise.all(agents.map(async (agent, index) => {
        const execution = await provider.runAgent(agent, request.task, request.context);
        return {
            evidence_id: execution.requestId ?? `${agent}:${index}`,
            claim: execution.text,
            provider: execution.provider,
            model: execution.model,
            ...(execution.requestId ? { request_id: execution.requestId } : {}),
            agent,
            attempts: execution.attempts ?? 1,
            latency_ms: execution.latencyMs,
            verified: false,
            reliability: 0.5,
            freshness: 1.0,
            relevance: 1.0
        };
    }));
    return { task: request.task, evidence };
}
