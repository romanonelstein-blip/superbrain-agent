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
    if (!tenantId.trim() || !signalId.trim()) {
      throw new Error('Execution identity must not be empty');
    }
    // Length-delimited JSON avoids ambiguous concatenations. Raw identities,
    // provider credentials, request data and results are never written to disk.
    const key = createHash('sha256').update(JSON.stringify([tenantId, signalId])).digest('hex');
    await mkdir(this.directory, { recursive: true, mode: 0o700 });

    let handle;
    try {
      handle = await open(join(this.directory, `${key}.claim`), 'wx', 0o600);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'EEXIST') return 'ALREADY_CLAIMED';
      throw new Error('Signal execution store unavailable');
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
  }
}
