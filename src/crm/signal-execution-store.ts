import { createHash } from 'node:crypto';
import { mkdir, open } from 'node:fs/promises';
import { resolve, join } from 'node:path';

export interface NovaProspectsExecutionStore {
  /** Atomically reserve before any provider work. Never automatically release. */
  claim(tenantId: string, signalId: string): Promise<'CLAIMED' | 'ALREADY_CLAIMED'>;
}

/** Single-host, persistent at-most-once guard on a trusted local filesystem. */
export class FileSignalExecutionStore implements NovaProspectsExecutionStore {
  private readonly directory: string;

  constructor(directory: string) {
    if (!directory.trim()) throw new Error('Execution store directory must not be empty');
    this.directory = resolve(directory);
  }

  async claim(tenantId: string, signalId: string): Promise<'CLAIMED' | 'ALREADY_CLAIMED'> {
    const canonicalTenantId = tenantId.trim();
    const canonicalSignalId = signalId.trim();
    if (!canonicalTenantId || !canonicalSignalId) {
      throw new Error('Execution identity must not be empty');
    }
    // Canonicalizing only surrounding whitespace prevents accidental replay
    // bypass without changing case-sensitive application identifiers.
    const key = createHash('sha256')
      .update(JSON.stringify([canonicalTenantId, canonicalSignalId]))
      .digest('hex');

    try {
      await mkdir(this.directory, { recursive: true, mode: 0o700 });

      let handle;
      try {
        handle = await open(join(this.directory, `${key}.claim`), 'wx', 0o600);
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code === 'EEXIST') return 'ALREADY_CLAIMED';
        throw error;
      }

      try {
        await handle.writeFile('{"version":1}\n', 'utf8');
        await handle.sync();
      } finally {
        await handle.close();
      }
      // Even a partial write is retained as a claim. Uncertain execution must
      // require operator reconciliation instead of automatically spending again.
      return 'CLAIMED';
    } catch {
      // Filesystem failures can contain private paths. Expose only a stable,
      // non-sensitive store error to direct callers as well as the executor.
      throw new Error('Signal execution store unavailable');
    }
  }
}
