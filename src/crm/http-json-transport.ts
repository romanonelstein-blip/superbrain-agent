export type JsonHttpMethod = 'GET' | 'POST';

export type JsonHttpQueryValue = string | number | boolean | readonly string[] | undefined;

export interface JsonHttpRequest {
  method: JsonHttpMethod;
  url: string;
  headers?: Readonly<Record<string, string>>;
  query?: Readonly<Record<string, JsonHttpQueryValue>>;
  body?: Readonly<Record<string, unknown>>;
  timeoutMs?: number;
  /** Maximum response body size in bytes. Defaults to 1 MiB. */
  maxResponseBytes?: number;
}

export interface JsonHttpResponse {
  status: number;
  body: unknown;
}

export interface JsonHttpTransport {
  request(input: JsonHttpRequest): Promise<JsonHttpResponse>;
}

const DEFAULT_MAX_RESPONSE_BYTES = 1_048_576;

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

async function readResponseText(response: Response, maxBytes: number): Promise<string> {
  const contentLength = response.headers.get('content-length');
  if (contentLength !== null && /^\d+$/.test(contentLength) && Number(contentLength) > maxBytes) {
    // Reject from headers before buffering the body, but cancel it so the fetch
    // implementation can release the connection and stop receiving data.
    void response.body?.cancel().catch(() => undefined);
    throw new Error(`HTTP response exceeds maximum size of ${maxBytes} bytes`);
  }

  if (!response.body) return '';

  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let totalBytes = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    if (!value) continue;

    totalBytes += value.byteLength;
    if (totalBytes > maxBytes) {
      // Do not wait for cancellation to settle before reporting the size error.
      void reader.cancel().catch(() => undefined);
      throw new Error(`HTTP response exceeds maximum size of ${maxBytes} bytes`);
    }
    chunks.push(value);
  }

  const bytes = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return new TextDecoder().decode(bytes);
}

export class FetchJsonHttpTransport implements JsonHttpTransport {
  async request(input: JsonHttpRequest): Promise<JsonHttpResponse> {
    const maxResponseBytes = input.maxResponseBytes ?? DEFAULT_MAX_RESPONSE_BYTES;
    if (!Number.isSafeInteger(maxResponseBytes) || maxResponseBytes <= 0) {
      throw new RangeError('maxResponseBytes must be a positive safe integer');
    }

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

      const text = await readResponseText(response, maxResponseBytes);
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
