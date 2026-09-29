export type JsonHttpMethod = 'GET' | 'POST';

export type JsonHttpQueryValue = string | number | boolean | readonly string[] | undefined;

export interface JsonHttpRequest {
  method: JsonHttpMethod;
  url: string;
  headers?: Readonly<Record<string, string>>;
  query?: Readonly<Record<string, JsonHttpQueryValue>>;
  body?: Readonly<Record<string, unknown>>;
  timeoutMs?: number;
}

export interface JsonHttpResponse {
  status: number;
  body: unknown;
}

export interface JsonHttpTransport {
  request(input: JsonHttpRequest): Promise<JsonHttpResponse>;
}

function appendQuery(url: URL, query: JsonHttpRequest['query']): void {
  if (!query) return;

  for (const [key, value] of Object.entries(query)) {
    if (value === undefined) continue;
    if (Array.isArray(value)) {
      value.forEach((item) => url.searchParams.append(key, String(item)));
      continue;
    }
    url.searchParams.set(key, String(value));
  }
}

export class FetchJsonHttpTransport implements JsonHttpTransport {
  async request(input: JsonHttpRequest): Promise<JsonHttpResponse> {
    const url = new URL(input.url);
    appendQuery(url, input.query);

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), input.timeoutMs ?? 8_000);

    try {
      const response = await fetch(url, {
        method: input.method,
        // Provider credentials use custom headers. Never follow an upstream
        // redirect that could forward those headers or prospect data elsewhere.
        redirect: 'error',
        headers: {
          accept: 'application/json',
          ...(input.body ? { 'content-type': 'application/json' } : {}),
          ...input.headers,
        },
        body: input.body ? JSON.stringify(input.body) : undefined,
        signal: controller.signal,
      });

      const text = await response.text();
      let body: unknown = null;
      if (text.length > 0) {
        try {
          body = JSON.parse(text) as unknown;
        } catch {
          body = text;
        }
      }

      return { status: response.status, body };
    } finally {
      clearTimeout(timeout);
    }
  }
}
