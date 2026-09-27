export class ProviderHttpError extends Error {
    provider;
    status;
    constructor(provider, status, message) {
        super(`${provider} API error (${status}): ${message}`);
        this.provider = provider;
        this.status = status;
        this.name = "ProviderHttpError";
    }
}
export function defaultFetch() {
    if (typeof globalThis.fetch !== "function") {
        throw new Error("Global fetch is unavailable. Superbrain requires Node.js 20+.");
    }
    return globalThis.fetch.bind(globalThis);
}
export async function fetchJson(provider, fetchImpl, url, init, timeoutMs) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    const start = Date.now();
    try {
        const response = await fetchImpl(url, { ...init, signal: controller.signal });
        const latencyMs = Date.now() - start;
        const raw = await response.text();
        let data = {};
        if (raw) {
            try {
                data = JSON.parse(raw);
            }
            catch {
                data = { raw };
            }
        }
        if (!response.ok) {
            const message = data?.error?.message ??
                data?.message ??
                data?.raw ??
                response.statusText ??
                "Unknown provider error";
            throw new ProviderHttpError(provider, response.status, String(message));
        }
        return { data, latencyMs, response };
    }
    finally {
        clearTimeout(timer);
    }
}
export function env(name) {
    const proc = globalThis.process;
    const value = proc?.env?.[name];
    return typeof value === "string" && value.trim() ? value.trim() : undefined;
}
export function timeoutFromEnv() {
    const raw = env("SUPERBRAIN_PROVIDER_TIMEOUT_MS");
    const parsed = raw ? Number(raw) : 60_000;
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 60_000;
}
