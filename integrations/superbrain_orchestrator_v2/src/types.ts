export type Complexity = "low" | "medium" | "high";

export type AgentName =
  | "research"
  | "strategy"
  | "builder"
  | "business"
  | "finance"
  | "critic"
  | "verifier";

export type ProviderName = "openai" | "anthropic" | "gemini" | "mock";

export interface OrchestrationRequest {
  task: string;
  context?: Record<string, unknown>;
  preferredAgents?: AgentName[];
}

export interface ProviderExecution {
  text: string;
  provider: ProviderName;
  model: string;
  latencyMs: number;
  requestId?: string;
  attempts?: number;
  resilience?: {
    attemptedProviders: ProviderName[];
    failures: Array<{
      provider: ProviderName;
      kind: string;
      retryable: boolean;
      status?: number;
    }>;
    costUnits: number;
    totalLatencyMs: number;
  };
}

export interface AgentResult {
  agent: AgentName;
  output: string;
  provider?: ProviderName;
  model?: string;
  latencyMs?: number;
  requestId?: string;
  attempts?: number;
  claims?: string[];
  confidence?: number;
}

export interface VerificationResult {
  verified: boolean;
  confidence: number;
  issues: string[];
}

export interface OrchestrationResult {
  task: string;
  complexity: Complexity;
  agentsUsed: AgentName[];
  outputs: AgentResult[];
  disagreements: string[];
  verification: VerificationResult;
  finalAnswer: string;
}
