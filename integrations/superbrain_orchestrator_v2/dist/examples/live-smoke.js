import { runNexusProviderMission } from "../src/nexus-bridge.js";
import { createProviderRouterFromEnv } from "../src/providers/factory.js";
const provider = createProviderRouterFromEnv();
const result = await runNexusProviderMission(provider, {
    task: "Research and propose a robust architecture for a multi-model AI orchestration service.",
    context: {
        constraint: "Prefer evidence, explicit uncertainty, and provider failover."
    }
});
console.log(JSON.stringify({
    task: result.task,
    evidenceCount: result.evidence.length,
    evidence: result.evidence.map(item => ({
        agent: item.agent,
        provider: item.provider,
        model: item.model,
        requestId: item.request_id,
        latencyMs: item.latency_ms,
        attempts: item.attempts,
        verified: item.verified
    }))
}, null, 2));
