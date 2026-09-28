import { mkdtemp, rm, readdir, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { pathToFileURL } from 'node:url';
import { FileSignalExecutionStore, type NovaProspectsExecutionStore } from '../crm/signal-execution-store';
import {
  NovaProspectsSignalExecutor, type NovaProspectsSignalPlan,
  type CrmDataResolver,
} from '../crm/novaprospects-signal-planner';
import type { CrmDataGatewayResponse } from '../crm/data-gateway';

class CountingResolver implements CrmDataResolver {
  executions = 0;
  async resolve(): Promise<CrmDataGatewayResponse> {
    this.executions += 1;
    return { result: null, attempts: [{ providerId: 'test', state: 'NOT_FOUND' }] };
  }
}

function plan(tenantId = 'tenant-a', signalId = 'signal-a'): NovaProspectsSignalPlan {
  return {
    tenantId, signalId, prospectId: 'prospect-a', maxProviderAttempts: 1,
    requests: [{ capability: 'EMAIL_VERIFY', input: { email: 'private@example.com' } }],
  };
}

describe('persistent signal execution guard', (): void => {
  let directory: string;
  beforeEach(async (): Promise<void> => { directory = await mkdtemp(join(tmpdir(), 'signal-guard-')); });
  afterEach(async (): Promise<void> => { await rm(directory, { recursive: true, force: true }); });

  test('reserves atomically across processes and survives their exit', async (): Promise<void> => {
    const run = promisify(execFile);
    const moduleUrl = pathToFileURL(resolve('dist/crm/signal-execution-store.js')).href;
    const script = `
      const { FileSignalExecutionStore } = await import(process.argv[1]);
      const store = new FileSignalExecutionStore(process.argv[2]);
      console.log(await store.claim('tenant', 'signal'));
    `;
    const outputs = await Promise.all(Array.from({ length: 4 }, async () => {
      const result = await run(process.execPath, ['--input-type=module', '-e', script, moduleUrl, directory]);
      return result.stdout.trim();
    }));
    expect(outputs.filter((output) => output === 'CLAIMED')).toHaveLength(1);
    expect(outputs.filter((output) => output === 'ALREADY_CLAIMED')).toHaveLength(3);
    expect(await new FileSignalExecutionStore(directory).claim('tenant', 'signal')).toBe('ALREADY_CLAIMED');
  });

  test('canonicalizes surrounding identity whitespace to prevent replay aliases', async (): Promise<void> => {
    const store = new FileSignalExecutionStore(directory);
    expect(await store.claim('tenant', 'signal')).toBe('CLAIMED');
    expect(await store.claim(' tenant ', ' signal ')).toBe('ALREADY_CLAIMED');
    expect(await readdir(directory)).toHaveLength(1);
  });

  test('sanitizes direct filesystem failures without leaking private paths', async (): Promise<void> => {
    const privatePath = join(directory, 'private-store-path');
    await writeFile(privatePath, 'not a directory');
    const store = new FileSignalExecutionStore(privatePath);
    let message = '';
    try {
      await store.claim('tenant', 'signal');
    } catch (error) {
      message = error instanceof Error ? error.message : String(error);
    }
    expect(message).toBe('Signal execution store unavailable');
    expect(message).not.toContain(privatePath);
  });

  test('retains incomplete claims rather than risking a repeated provider call', async (): Promise<void> => {
    const store = new FileSignalExecutionStore(directory);
    await store.claim('tenant', 'signal');
    const [name] = await readdir(directory);
    await writeFile(join(directory, name), '');
    expect(await store.claim('tenant', 'signal')).toBe('ALREADY_CLAIMED');
  });

  test('only one concurrent executor can reserve a signal', async (): Promise<void> => {
    const resolver = new CountingResolver();
    const results = await Promise.all(Array.from({ length: 12 }, async () => {
      const executor = new NovaProspectsSignalExecutor(resolver, new FileSignalExecutionStore(directory));
      return executor.execute(plan());
    }));
    expect(resolver.executions).toBe(1);
    expect(results.filter((result) => result.stoppedReason === 'SIGNAL_ALREADY_CLAIMED')).toHaveLength(11);
  });

  test('a fresh store instance cannot replay the same signal with changed input', async (): Promise<void> => {
    const resolver = new CountingResolver();
    await new NovaProspectsSignalExecutor(resolver, new FileSignalExecutionStore(directory)).execute(plan());
    const changed = { ...plan(), requests: [{ capability: 'COMPANY_ENRICHMENT' as const, input: {} }] };
    const result = await new NovaProspectsSignalExecutor(resolver, new FileSignalExecutionStore(directory))
      .execute(changed);
    expect(result.stoppedReason).toBe('SIGNAL_ALREADY_CLAIMED');
    expect(resolver.executions).toBe(1);
  });

  test('separates tenants and signal ids without persisting prospect data', async (): Promise<void> => {
    const resolver = new CountingResolver();
    const executor = new NovaProspectsSignalExecutor(resolver, new FileSignalExecutionStore(directory));
    await executor.execute(plan());
    await executor.execute(plan('tenant-b'));
    await executor.execute(plan('tenant-a', 'signal-b'));
    expect(resolver.executions).toBe(3);
    const names = await readdir(directory);
    expect(names).toHaveLength(3);
    for (const name of names) {
      expect(name).toMatch(/^[a-f0-9]{64}\.claim$/);
      expect(await readFile(join(directory, name), 'utf8')).toBe('{"version":1}\n');
    }
  });

  test('retains the reservation after an uncertain provider failure', async (): Promise<void> => {
    const broken: CrmDataResolver = {
      async resolve(): Promise<CrmDataGatewayResponse> { throw new Error('uncertain execution'); },
    };
    await expect(new NovaProspectsSignalExecutor(broken, new FileSignalExecutionStore(directory)).execute(plan()))
      .rejects.toThrow('uncertain execution');
    const resolver = new CountingResolver();
    const result = await new NovaProspectsSignalExecutor(resolver, new FileSignalExecutionStore(directory)).execute(plan());
    expect(result.stoppedReason).toBe('SIGNAL_ALREADY_CLAIMED');
    expect(resolver.executions).toBe(0);
  });

  test('blocks provider work when the store is unavailable and sanitizes errors', async (): Promise<void> => {
    const store: NovaProspectsExecutionStore = {
      async claim(): Promise<'CLAIMED'> { throw new Error('private filesystem path'); },
    };
    const resolver = new CountingResolver();
    const result = await new NovaProspectsSignalExecutor(resolver, store).execute(plan());
    expect(result.stoppedReason).toBe('SIGNAL_STORE_UNAVAILABLE');
    expect(resolver.executions).toBe(0);
    expect(JSON.stringify(result)).not.toContain('private');
  });

  test('fails closed for a real invalid storage directory', async (): Promise<void> => {
    const path = join(directory, 'file');
    await writeFile(path, 'not a directory');
    const resolver = new CountingResolver();
    const result = await new NovaProspectsSignalExecutor(resolver, new FileSignalExecutionStore(path)).execute(plan());
    expect(result.stoppedReason).toBe('SIGNAL_STORE_UNAVAILABLE');
    expect(resolver.executions).toBe(0);
  });

  test('does not reserve empty plans or invalid identities', async (): Promise<void> => {
    const executor = new NovaProspectsSignalExecutor(new CountingResolver(), new FileSignalExecutionStore(directory));
    await executor.execute({ ...plan(), requests: [] });
    await expect(executor.execute(plan('  '))).rejects.toThrow('tenantId must not be empty');
    expect(await readdir(directory)).toEqual([]);
  });
});
