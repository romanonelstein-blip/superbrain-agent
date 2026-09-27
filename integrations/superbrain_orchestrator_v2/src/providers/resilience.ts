import { AgentName, ProviderName } from "../types.js";
import { ProviderHttpError } from "./http.js";

export type ProviderFailureKind =
  | "timeout"
  | "rate_limit"
  | "auth"
  | "bad_request"
  | "server"
  | "network"
  | "circuit_open"
  | "budget_exhausted"
  | "provider_not_allowed"
  | "model_not_allowed"
  | "invalid_response"
  | "unknown";

export interface ProviderFailureRecord {
  provider: ProviderName;
  kind: ProviderFailureKind;
  retryable: boolean;
  status?: number;
}

export interface ProviderResilienceMetadata {
  attemptedProviders: ProviderName[];
  failures: ProviderFailureRecord[];
  costUnits: number;
  totalLatencyMs: number;
}

export interface ProviderResiliencePolicy {
  allowedProviders: ProviderName[];
  allowedModels: Partial<Record<ProviderName, string[]>>;
  maxAttemptsPerProvider: number;
  maxTotalAttempts: number;
  providerTimeoutMs: number;
  maxTotalLatencyMs: number;
  maxCostUnits: number;
  costUnitsPerAttempt: Partial<Record<ProviderName, number>>;
  retryBaseDelayMs: number;
  circuitBreakerFailureThreshold: number;
  circuitBreakerCooldownMs: number;
  rateLimitMaxAttempts: number;
  rateLimitWindowMs: number;
}

export const DEFAULT_RESILIENCE_POLICY: ProviderResiliencePolicy = {
  allowedProviders: ["openai", "anthropic", "gemini", "mock"],
  allowedModels: {},
  maxAttemptsPerProvider: 2,
  maxTotalAttempts: 6,
  providerTimeoutMs: 60_000,
  maxTotalLatencyMs: 120_000,
  maxCostUnits: 12,
  costUnitsPerAttempt: {
    openai: 1,
    anthropic: 1,
    gemini: 1,
    mock: 0
  },
  retryBaseDelayMs: 250,
  circuitBreakerFailureThreshold: 3,
  circuitBreakerCooldownMs: 30_000,
  rateLimitMaxAttempts: 60,
  rateLimitWindowMs: 60_000
};

export interface ClassifiedProviderFailure {
  kind: ProviderFailureKind;
  retryable: boolean;
  status?: number;
}

export function classifyProviderFailure(error: unknown): ClassifiedProviderFailure {
  if (error instanceof ProviderHttpError) {
    if (error.status === 408) return { kind: "timeout", retryable: true, status: error.status };
    if (error.status === 429) return { kind: "rate_limit", retryable: true, status: error.status };
    if (error.status === 401 || error.status === 403) {
      return { kind: "auth", retryable: false, status: error.status };
    }
    if (error.status >= 500) return { kind: "server", retryable: true, status: error.status };
    return { kind: "bad_request", retryable: false, status: error.status };
  }

  if (error instanceof Error) {
    if (error.name === "AbortError" || /timed?\s*out|timeout/i.test(error.message)) {
      return { kind: "timeout", retryable: true };
    }
    if (error instanceof TypeError || /network|fetch failed|econnreset|eai_again|enotfound/i.test(error.message)) {
      return { kind: "network", retryable: true };
    }
    if (/no text output|invalid response/i.test(error.message)) {
      return { kind: "invalid_response", retryable: false };
    }
  }

  return { kind: "unknown", retryable: false };
}

export function sanitizeProviderError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  return message
    .replace(/sk-[A-Za-z0-9_-]+/g, "[redacted]")
    .replace(/AIza[A-Za-z0-9_-]+/g, "[redacted]")
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer [redacted]")
    .replace(/(?:api[_-]?key|x-api-key)\s*[:=]\s*[^\s,;]+/gi, "$1=[redacted]")
    .slice(0, 500);
}

export function assertPositiveInteger(name: string, value: number): void {
  if (!Number.isInteger(value) || value <= 0) {
    throw new Error(`${name} must be a positive integer.`);
  }
}

export function assertPositiveNumber(name: string, value: number): void {
  if (!Number.isFinite(value) || value <= 0) {
    throw new Error(`${name} must be positive.`);
  }
}

export function validatePolicy(policy: ProviderResiliencePolicy): void {
  assertPositiveInteger("maxAttemptsPerProvider", policy.maxAttemptsPerProvider);
  assertPositiveInteger("maxTotalAttempts", policy.maxTotalAttempts);
  assertPositiveNumber("providerTimeoutMs", policy.providerTimeoutMs);
  assertPositiveNumber("maxTotalLatencyMs", policy.maxTotalLatencyMs);
  assertPositiveNumber("maxCostUnits", policy.maxCostUnits);
  if (!Number.isFinite(policy.retryBaseDelayMs) || policy.retryBaseDelayMs < 0) {
    throw new Error("retryBaseDelayMs must be zero or positive.");
  }
  assertPositiveInteger("circuitBreakerFailureThreshold", policy.circuitBreakerFailureThreshold);
  assertPositiveNumber("circuitBreakerCooldownMs", policy.circuitBreakerCooldownMs);
  assertPositiveInteger("rateLimitMaxAttempts", policy.rateLimitMaxAttempts);
  assertPositiveNumber("rateLimitWindowMs", policy.rateLimitWindowMs);
}

export interface ProviderRuntimeHooks {
  now?: () => number;
  sleep?: (ms: number) => Promise<void>;
}

export interface ProviderRequestContext {
  agent: AgentName;
  task: string;
}
