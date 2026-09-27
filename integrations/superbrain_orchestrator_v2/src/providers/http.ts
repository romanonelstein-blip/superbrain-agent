export type FetchLike = (
  input: RequestInfo | URL,
  init?: RequestInit
) => Promise<Response>;

export class ProviderHttpError extends Error {
  constructor(
    public readonly provider: string,
    public readonly status: number,
    message: string
  ) {
    super(`${provider} API error (${status}): ${message}`);
    this.name = "ProviderHttpError";
  }
}

export function defaultFetch(): FetchLike {
  if (typeof globalThis.fetch !== "function") {
    throw new Error("Global fetch is unavailable. Superbrain requires Node.js 20+.");
  }
  return globalThis.fetch.bind(globalThis);
}

export async function fetchJson(
  provider: string,
  fetchImpl: FetchLike,
  url: string,
  init: RequestInit,
  timeoutMs: number
): Promise<{ data: any; latencyMs: number; response: Response }> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const start = Date.now();

  try {
    const response = await fetchImpl(url, { ...init, signal: controller.signal });
    const latencyMs = Date.now() - start;
    const raw = await response.text();

    let data: any = {};
    if (raw) {
      try {
        data = JSON.parse(raw);
      } catch {
        data = { raw };
      }
    }

    if (!response.ok) {
      const message =
        data?.error?.message ??
        data?.message ??
        data?.raw ??
        response.statusText ??
        "Unknown provider error";
      throw new ProviderHttpError(provider, response.status, String(message));
    }

    return { data, latencyMs, response };
  } finally {
    clearTimeout(timer);
  }
}

export function env(name: string): string | undefined {
  const proc = (globalThis as any).process;
  const value = proc?.env?.[name];
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

export function timeoutFromEnv(): number {
  const raw = env("SUPERBRAIN_PROVIDER_TIMEOUT_MS");
  const parsed = raw ? Number(raw) : 60_000;
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 60_000;
}
