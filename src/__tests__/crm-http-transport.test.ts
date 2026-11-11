import { jest } from '@jest/globals';
import { createServer, type Server } from 'node:http';
import type { AddressInfo } from 'node:net';
import { FetchJsonHttpTransport } from '../crm/http-json-transport';

async function listen(server: Server): Promise<string> {
  await new Promise<void>((resolve) => { server.listen(0, '127.0.0.1', resolve); });
  return `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
}

async function close(server: Server): Promise<void> {
  server.closeAllConnections();
  await new Promise<void>((resolve, reject) => {
    server.close((error) => { if (error) reject(error); else resolve(); });
  });
}

describe('CRM HTTP transport credential boundary', (): void => {
  test.each([301, 302, 303, 307, 308])(
    'rejects HTTP %s instead of forwarding custom authentication headers',
    async (status): Promise<void> => {
      let forwardedRequests = 0;
      const target = createServer((_request, response): void => {
        forwardedRequests += 1;
        response.end('{}');
      });
      const targetUrl = await listen(target);
      const origin = createServer((_request, response): void => {
        response.writeHead(status, { location: targetUrl });
        response.end();
      });
      const originUrl = await listen(origin);
      try {
        await expect(new FetchJsonHttpTransport().request({
          method: 'POST', url: originUrl,
          headers: { 'x-api-key': 'test-only', 'clay-api-key': 'test-only' },
          body: { email: 'synthetic@example.com' },
        })).rejects.toThrow();
        expect(forwardedRequests).toBe(0);
      } finally {
        await Promise.all([close(origin), close(target)]);
      }
    },
  );

  test.each([true, false])(
    'rejects oversized response bodies (content-length present: %s)',
    async (includeContentLength): Promise<void> => {
      const payload = '0123456789';
      const server = createServer((_request, response): void => {
        if (includeContentLength) response.writeHead(200, { 'content-length': Buffer.byteLength(payload) });
        else response.flushHeaders(); // Force chunked transfer, without an automatic Content-Length.
        response.end(payload);
      });
      const url = await listen(server);
      try {
        await expect(new FetchJsonHttpTransport().request({
          method: 'GET', url, maxResponseBytes: 8,
        })).rejects.toThrow('HTTP response exceeds maximum size of 8 bytes');
      } finally {
        await close(server);
      }
    },
  );

  test.each([0, -1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1])(
    'rejects invalid response size limit %s before fetching', async (maxResponseBytes): Promise<void> => {
    await expect(new FetchJsonHttpTransport().request({
      method: 'GET', url: 'invalid-url', maxResponseBytes,
    })).rejects.toThrow('maxResponseBytes must be a positive safe integer');
  });

  test('enforces the default 1 MiB limit on chunked responses', async (): Promise<void> => {
    const server = createServer((_request, response): void => {
      response.flushHeaders();
      response.end('x'.repeat(1_048_577));
    });
    const url = await listen(server);
    try {
      await expect(new FetchJsonHttpTransport().request({ method: 'GET', url }))
        .rejects.toThrow('HTTP response exceeds maximum size of 1048576 bytes');
    } finally { await close(server); }
  });

  test.each([4, 5])('counts UTF-8 bytes across chunks at limit %s', async (maxResponseBytes): Promise<void> => {
    const bytes = new TextEncoder().encode('"€"'); // Five bytes, three characters.
    const stream = new ReadableStream<Uint8Array>({
      start(controller): void {
        controller.enqueue(bytes.slice(0, 2));
        controller.enqueue(bytes.slice(2));
        controller.close();
      },
    });
    const mock = jest.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(stream));
    try {
      const result = new FetchJsonHttpTransport().request({ method: 'GET', url: 'http://fixture.invalid', maxResponseBytes });
      if (maxResponseBytes === 4) await expect(result).rejects.toThrow('maximum size of 4 bytes');
      else await expect(result).resolves.toEqual({ status: 200, body: '€' });
    } finally { mock.mockRestore(); }
  });

  test.each(['header', 'stream'] as const)(
    'cancels an oversized %s response without waiting for cancellation', async (mode): Promise<void> => {
      let cancelled = false;
      const stream = new ReadableStream<Uint8Array>({
        start(controller): void { controller.enqueue(new Uint8Array(9)); },
        cancel(): Promise<void> {
          cancelled = true;
          return new Promise<void>(() => { /* Simulate cancellation that never settles. */ });
        },
      });
      const response = new Response(stream, { headers: mode === 'header' ? { 'content-length': '9' } : {} });
      const mock = jest.spyOn(globalThis, 'fetch').mockResolvedValue(response);
      try {
        await expect(new FetchJsonHttpTransport().request({
          method: 'GET', url: 'http://fixture.invalid', maxResponseBytes: 8,
        })).rejects.toThrow('maximum size of 8 bytes');
        expect(cancelled).toBe(true);
      } finally { mock.mockRestore(); }
    }, 1000,
  );

  test('keeps the request timeout active after receiving response headers and a partial body', async (): Promise<void> => {
    let bodyStarted = false;
    const server = createServer((_request, response): void => {
      bodyStarted = true;
      response.writeHead(200);
      response.write('{'); // Deliberately never finish the body.
    });
    const url = await listen(server);
    try {
      await expect(new FetchJsonHttpTransport().request({ method: 'GET', url, timeoutMs: 150 }))
        .rejects.toThrow();
      expect(bodyStarted).toBe(true);
    } finally { await close(server); }
  });

  test('still sends credentials and JSON to the intended provider endpoint', async (): Promise<void> => {
    let authentication: string | string[] | undefined;
    let body = '';
    let query = '';
    const server = createServer((request, response): void => {
      authentication = request.headers['x-api-key'];
      query = request.url ?? '';
      request.on('data', (chunk: Buffer): void => { body += chunk.toString(); });
      request.on('end', (): void => {
        response.writeHead(200, { 'content-type': 'application/json' });
        response.end('{"ok":true}');
      });
    });
    const url = await listen(server);
    try {
      const response = await new FetchJsonHttpTransport().request({
        method: 'POST', url, headers: { 'x-api-key': 'test-only' },
        query: { page: 1 }, body: { name: 'synthetic' },
      });
      expect(response).toEqual({ status: 200, body: { ok: true } });
      expect(authentication).toBe('test-only');
      expect(query).toBe('/?page=1');
      expect(JSON.parse(body)).toEqual({ name: 'synthetic' });
    } finally {
      await close(server);
    }
  });
});
