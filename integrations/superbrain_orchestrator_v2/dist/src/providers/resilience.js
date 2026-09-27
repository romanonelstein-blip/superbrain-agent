import { ProviderHttpError } from "./http.js";
export const DEFAULT_RESILIENCE_POLICY = {
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
export function classifyProviderFailure(error) {
    if (error instanceof ProviderHttpError) {
        if (error.status === 408)
            return { kind: "timeout", retryable: true, status: error.status };
        if (error.status === 429)
            return { kind: "rate_limit", retryable: true, status: error.status };
        if (error.status === 401 || error.status === 403) {
            return { kind: "auth", retryable: false, status: error.status };
        }
        if (error.status >= 500)
            return { kind: "server", retryable: true, status: error.status };
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
export function sanitizeProviderError(error) {
    const message = error instanceof Error ? error.message : String(error);
    return message
        .replace(/sk-[A-Za-z0-9_-]+/g, "[redacted]")
        .replace(/AIza[A-Za-z0-9_-]+/g, "[redacted]")
        .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/gi, "Bearer [redacted]")
        .replace(/(?:api[_-]?key|x-api-key)\s*[:=]\s*[^\s,;]+/gi, "$1=[redacted]")
        .slice(0, 500);
}
export function assertPositiveInteger(name, value) {
    if (!Number.isInteger(value) || value <= 0) {
        throw new Error(`${name} must be a positive integer.`);
    }
}
export function assertPositiveNumber(name, value) {
    if (!Number.isFinite(value) || value <= 0) {
        throw new Error(`${name} must be positive.`);
    }
}
export function validatePolicy(policy) {
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
