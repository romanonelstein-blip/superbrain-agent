import { env } from "./http.js";
import { OpenAIProvider } from "./openai.js";
import { AnthropicProvider } from "./anthropic.js";
import { GeminiProvider } from "./gemini.js";
import { ProviderRouter } from "./router.js";
export function createProviderRouterFromEnv(policy = {}) {
    const providers = [];
    if (env("OPENAI_API_KEY"))
        providers.push(new OpenAIProvider());
    if (env("ANTHROPIC_API_KEY"))
        providers.push(new AnthropicProvider());
    if (env("GEMINI_API_KEY"))
        providers.push(new GeminiProvider());
    if (!providers.length) {
        throw new Error("No model provider credentials found. Configure at least one of " +
            "OPENAI_API_KEY, ANTHROPIC_API_KEY, or GEMINI_API_KEY.");
    }
    const allowedProviders = parseProviderList(env("SUPERBRAIN_PROVIDER_ALLOWLIST"));
    const resilience = {
        ...(allowedProviders.length ? { allowedProviders } : {}),
        maxAttemptsPerProvider: positiveIntEnv("SUPERBRAIN_PROVIDER_MAX_ATTEMPTS", 2),
        maxTotalAttempts: positiveIntEnv("SUPERBRAIN_PROVIDER_MAX_TOTAL_ATTEMPTS", 6),
        providerTimeoutMs: positiveNumberEnv("SUPERBRAIN_PROVIDER_ROUTER_TIMEOUT_MS", 60_000),
        maxTotalLatencyMs: positiveNumberEnv("SUPERBRAIN_PROVIDER_MAX_TOTAL_LATENCY_MS", 120_000),
        maxCostUnits: positiveNumberEnv("SUPERBRAIN_PROVIDER_COST_BUDGET", 12),
        circuitBreakerFailureThreshold: positiveIntEnv("SUPERBRAIN_PROVIDER_CIRCUIT_THRESHOLD", 3),
        circuitBreakerCooldownMs: positiveNumberEnv("SUPERBRAIN_PROVIDER_CIRCUIT_COOLDOWN_MS", 30_000),
        rateLimitMaxAttempts: positiveIntEnv("SUPERBRAIN_PROVIDER_RATE_LIMIT", 60),
        rateLimitWindowMs: positiveNumberEnv("SUPERBRAIN_PROVIDER_RATE_WINDOW_MS", 60_000)
    };
    return new ProviderRouter(providers, policy, { resilience });
}
function positiveIntEnv(name, fallback) {
    const value = Number(env(name));
    return Number.isInteger(value) && value > 0 ? value : fallback;
}
function positiveNumberEnv(name, fallback) {
    const value = Number(env(name));
    return Number.isFinite(value) && value > 0 ? value : fallback;
}
function parseProviderList(raw) {
    if (!raw)
        return [];
    const allowed = new Set(["openai", "anthropic", "gemini", "mock"]);
    return raw
        .split(",")
        .map(value => value.trim().toLowerCase())
        .filter((value) => allowed.has(value));
}
