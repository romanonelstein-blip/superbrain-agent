import { ModelProvider } from "./provider.js";
import { routeAgents } from "./router.js";
import { AgentName, OrchestrationRequest } from "./types.js";

export interface NexusProviderEvidence {
  evidence_id: string;
  claim: string;
  provider: string;
  model: string;
  request_id?: string;
  agent: string;
  attempts: number;
  latency_ms: number;
  verified: false;
  reliability: number;
  freshness: number;
  relevance: number;
}

export interface NexusProviderBatch {
  task: string;
  evidence: NexusProviderEvidence[];
}

export async function runNexusProviderMission(
  provider: ModelProvider,
  request: OrchestrationRequest
): Promise<NexusProviderBatch> {
  const agents = routeAgents(request).filter(
    (agent): agent is AgentName => !["critic", "verifier"].includes(agent)
  );

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
      verified: false as const,
      reliability: 0.5,
      freshness: 1.0,
      relevance: 1.0
    };
  }));

  return { task: request.task, evidence };
}
