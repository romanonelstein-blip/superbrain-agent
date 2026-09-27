import { classifyProviderFailure, DEFAULT_RESILIENCE_POLICY, sanitizeProviderError, validatePolicy } from "./resilience.js";
const DEFAULT_POLICY = {
    research: ["gemini", "openai", "anthropic"],
    strategy: ["openai", "anthropic", "gemini"],
    builder: ["anthropic", "openai", "gemini"],
    business: ["openai", "anthropic", "gemini"],
    finance: ["openai", "anthropic", "gemini"],
    critic: ["anthropic", "openai", "gemini"],
    verifier: ["openai", "anthropic", "gemini"]
};
export class ProviderRouter {
    name = "mock";
    model = "provider-router";
    providers;
    policy;
    resilience;
    now;
    sleep;
    circuits = new Map();
    attemptWindows = new Map();
    constructor(providers, policy = {}, options = {}) {
        this.providers = new Map(providers.map(provider => [provider.name, provider]));
        this.policy = {
            ...DEFAULT_POLICY,
            ...policy
        };
        this.resilience = {
            ...DEFAULT_RESILIENCE_POLICY,
            ...options.resilience,
            allowedModels: {
                ...DEFAULT_RESILIENCE_POLICY.allowedModels,
                ...(options.resilience?.allowedModels ?? {})
            },
            costUnitsPerAttempt: {
                ...DEFAULT_RESILIENCE_POLICY.costUnitsPerAttempt,
                ...(options.resilience?.costUnitsPerAttempt ?? {})
            }
        };
        validatePolicy(this.resilience);
        this.now = options.now ?? (() => Date.now());
        this.sleep = options.sleep ?? (ms => new Promise(resolve => setTimeout(resolve, ms)));
        if (!providers.length) {
            throw new Error("ProviderRouter requires at least one provider.");
        }
    }
    get availableProviders() {
        return [...this.providers.keys()];
    }
    async runAgent(agent, task, context) {
        const configuredOrder = this.policy[agent];
        const candidates = [
            ...configuredOrder.filter(name => this.providers.has(name)),
            ...this.availableProviders.filter(name => !configuredOrder.includes(name))
        ];
        const errors = [];
        const failures = [];
        const attemptedProviders = [];
        let attempts = 0;
        let costUnits = 0;
        const startedAt = this.now();
        for (const providerName of candidates) {
            const provider = this.providers.get(providerName);
            if (!provider)
                continue;
            if (!this.resilience.allowedProviders.includes(providerName)) {
                failures.push({ provider: providerName, kind: "provider_not_allowed", retryable: false });
                continue;
            }
            const allowedModels = this.resilience.allowedModels[providerName];
            if (allowedModels?.length && !allowedModels.includes(provider.model)) {
                failures.push({ provider: providerName, kind: "model_not_allowed", retryable: false });
                continue;
            }
            const circuit = this.circuits.get(providerName);
            if (circuit?.openUntil && circuit.openUntil > this.now()) {
                failures.push({ provider: providerName, kind: "circuit_open", retryable: true });
                continue;
            }
            if (circuit?.openUntil && circuit.openUntil <= this.now()) {
                this.circuits.set(providerName, { failures: 0, openUntil: 0 });
            }
            for (let providerAttempt = 1; providerAttempt <= this.resilience.maxAttemptsPerProvider; providerAttempt += 1) {
                const elapsed = this.now() - startedAt;
                if (attempts >= this.resilience.maxTotalAttempts || elapsed >= this.resilience.maxTotalLatencyMs) {
                    failures.push({ provider: providerName, kind: "budget_exhausted", retryable: false });
                    throw this.finalError(agent, errors, failures);
                }
                const attemptCost = this.resilience.costUnitsPerAttempt[providerName] ?? 1;
                if (costUnits + attemptCost > this.resilience.maxCostUnits) {
                    failures.push({ provider: providerName, kind: "budget_exhausted", retryable: false });
                    throw this.finalError(agent, errors, failures);
                }
                if (!this.consumeRateLimit(providerName)) {
                    failures.push({ provider: providerName, kind: "rate_limit", retryable: true });
                    errors.push(`${providerName}: local rate limit exceeded`);
                    break;
                }
                attempts += 1;
                costUnits += attemptCost;
                attemptedProviders.push(providerName);
                try {
                    const result = await this.runWithTimeout(provider.runAgent(agent, task, context), this.resilience.providerTimeoutMs);
                    this.circuits.set(providerName, { failures: 0, openUntil: 0 });
                    const totalLatencyMs = this.now() - startedAt;
                    if (totalLatencyMs > this.resilience.maxTotalLatencyMs) {
                        failures.push({ provider: providerName, kind: "budget_exhausted", retryable: false });
                        throw this.finalError(agent, errors, failures);
                    }
                    return {
                        ...result,
                        attempts,
                        resilience: {
                            attemptedProviders,
                            failures,
                            costUnits,
                            totalLatencyMs
                        }
                    };
                }
                catch (error) {
                    if (error instanceof Error && error.name === "ProviderRouterFinalError")
                        throw error;
                    const classified = classifyProviderFailure(error);
                    failures.push({ provider: providerName, ...classified });
                    errors.push(`${providerName}: ${sanitizeProviderError(error)}`);
                    this.recordFailure(providerName);
                    if (!classified.retryable || providerAttempt >= this.resilience.maxAttemptsPerProvider) {
                        break;
                    }
                    const delay = this.resilience.retryBaseDelayMs * Math.max(1, 2 ** (providerAttempt - 1));
                    if (delay > 0)
                        await this.sleep(delay);
                }
            }
        }
        throw this.finalError(agent, errors, failures);
    }
    consumeRateLimit(provider) {
        const now = this.now();
        const cutoff = now - this.resilience.rateLimitWindowMs;
        const recent = (this.attemptWindows.get(provider) ?? []).filter(ts => ts > cutoff);
        if (recent.length >= this.resilience.rateLimitMaxAttempts) {
            this.attemptWindows.set(provider, recent);
            return false;
        }
        recent.push(now);
        this.attemptWindows.set(provider, recent);
        return true;
    }
    recordFailure(provider) {
        const current = this.circuits.get(provider) ?? { failures: 0, openUntil: 0 };
        const failures = current.failures + 1;
        const openUntil = failures >= this.resilience.circuitBreakerFailureThreshold
            ? this.now() + this.resilience.circuitBreakerCooldownMs
            : 0;
        this.circuits.set(provider, { failures, openUntil });
    }
    async runWithTimeout(promise, timeoutMs) {
        let timer;
        try {
            return await Promise.race([
                promise,
                new Promise((_resolve, reject) => {
                    timer = setTimeout(() => {
                        const error = new Error(`Provider execution timed out after ${timeoutMs}ms.`);
                        error.name = "AbortError";
                        reject(error);
                    }, timeoutMs);
                })
            ]);
        }
        finally {
            if (timer)
                clearTimeout(timer);
        }
    }
    finalError(agent, errors, failures) {
        const summary = failures.map(f => `${f.provider}:${f.kind}`).join(", ");
        const detail = errors.join(" | ");
        const error = new Error(`All providers failed for agent "${agent}". failures=[${summary}]${detail ? ` ${detail}` : ""}`);
        error.name = "ProviderRouterFinalError";
        return error;
    }
}
