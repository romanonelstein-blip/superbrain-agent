import { createHash, randomUUID, timingSafeEqual } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import { dirname } from 'node:path';

export type MissionMode = 'ask' | 'research';
export type MasterDecisionAction = 'ACCEPT' | 'MODIFY' | 'RESEARCH_MORE' | 'OVERRIDE' | 'REJECT';

export interface MissionSummary {
  runId: string;
  question: string;
  status: 'running' | 'completed' | 'failed';
  finalValue?: string;
  createdAt: string;
}

export interface MissionEvidence {
  id: string;
  claim: string;
  verified: boolean;
  sourceId?: string;
  sourceFamily?: string;
  trustBoundary?: string;
  citation?: string;
  stance?: string;
}

export interface MissionAuditItem {
  stage: string;
  detail: string;
}

export interface MissionDraft {
  agent?: string;
  text?: string;
  verified?: boolean;
}

export interface MissionResponse {
  runId: string;
  nexusFinalValue: string;
  verificationNote?: string;
  draftResponses?: MissionDraft[];
}

export interface MasterDecisionRecord {
  action: MasterDecisionAction;
  note: string;
  createdAt: string;
}

export interface MissionDetail {
  run: MissionSummary;
  evidence: MissionEvidence[];
  audit: MissionAuditItem[];
  masterDecisions: MasterDecisionRecord[];
}

interface StoredMission extends MissionDetail {
  response?: MissionResponse;
}

interface MissionDatabase {
  version: 1;
  missions: StoredMission[];
}

export interface MissionExecutorStatus {
  interactiveMissionsAvailable: boolean;
  researchMissionsAvailable: boolean;
  configuredProviders: string[];
}

export interface MissionExecutionInput {
  runId: string;
  question: string;
  mode: MissionMode;
}

export interface MissionExecutionResult {
  nexusFinalValue: string;
  verificationNote?: string;
  draftResponses?: MissionDraft[];
  evidence: MissionEvidence[];
  audit: MissionAuditItem[];
}

export interface MissionExecutor {
  getStatus(): Promise<MissionExecutorStatus>;
  execute(input: MissionExecutionInput): Promise<MissionExecutionResult>;
}

export class UnavailableMissionExecutor implements MissionExecutor {
  async getStatus(): Promise<MissionExecutorStatus> {
    return {
      interactiveMissionsAvailable: false,
      researchMissionsAvailable: false,
      configuredProviders: [],
    };
  }

  async execute(input: MissionExecutionInput): Promise<MissionExecutionResult> {
    void input;
    throw new Error('No mission executor is configured.');
  }
}

export interface MissionControlServerConfig {
  token: string;
  dataPath: string;
  host?: string;
  port?: number;
  canonicalRuntime?: string;
  superBrainVersion?: string;
  apiVersion?: string;
  capabilities?: string[];
  executor?: MissionExecutor;
  maxBodyBytes?: number;
}

export interface MissionControlAddress {
  host: string;
  port: number;
  url: string;
}

class MissionStore {
  private readonly filePath: string;
  private loaded = false;
  private readonly records = new Map<string, StoredMission>();
  private writeQueue: Promise<void> = Promise.resolve();

  constructor(filePath: string) {
    this.filePath = filePath;
  }

  async list(): Promise<MissionSummary[]> {
    await this.load();
    return Array.from(this.records.values())
      .map((item): MissionSummary => ({ ...item.run }))
      .sort((a, b): number => b.createdAt.localeCompare(a.createdAt));
  }

  async get(runId: string): Promise<StoredMission | null> {
    await this.load();
    const item = this.records.get(runId);
    return item ? structuredClone(item) : null;
  }

  async upsert(item: StoredMission): Promise<void> {
    await this.load();
    this.records.set(item.run.runId, structuredClone(item));
    await this.persist();
  }

  async finalize(item: StoredMission): Promise<void> {
    await this.load();
    const current = this.records.get(item.run.runId);
    if (!current) throw new Error('Cannot finalize an unknown mission.');
    // Merge against the live record, not the snapshot taken before execution.
    // No await may separate reading it from replacing it: Master decisions
    // can arrive while the executor is running or a disk write is pending.
    this.records.set(item.run.runId, structuredClone({
      ...item,
      masterDecisions: current.masterDecisions,
      audit: [...current.audit, ...item.audit],
    }));
    await this.persist();
  }

  async addDecision(runId: string, decision: MasterDecisionRecord): Promise<StoredMission | null> {
    await this.load();
    const item = this.records.get(runId);
    if (!item) return null;
    item.masterDecisions.push(structuredClone(decision));
    item.audit.push({ stage: 'master_decision', detail: `Master decision recorded: ${decision.action}` });
    await this.persist();
    return structuredClone(item);
  }

  private async load(): Promise<void> {
    if (this.loaded) return;
    this.loaded = true;
    try {
      const raw = await readFile(this.filePath, 'utf8');
      const parsed = JSON.parse(raw) as MissionDatabase;
      if (parsed.version !== 1 || !Array.isArray(parsed.missions)) return;
      for (const mission of parsed.missions) {
        if (mission?.run?.runId) this.records.set(mission.run.runId, mission);
      }
    } catch (error) {
      const code = (error as NodeJS.ErrnoException).code;
      if (code !== 'ENOENT') throw error;
    }
  }

  private async persist(): Promise<void> {
    const snapshot: MissionDatabase = {
      version: 1,
      missions: Array.from(this.records.values()),
    };
    const write = async (): Promise<void> => {
      await mkdir(dirname(this.filePath), { recursive: true });
      const temporary = `${this.filePath}.${process.pid}.${Date.now()}.tmp`;
      await writeFile(temporary, JSON.stringify(snapshot, null, 2) + '\n', { encoding: 'utf8', mode: 0o600 });
      await rename(temporary, this.filePath);
    };
    const task = this.writeQueue.then(write, write);
    this.writeQueue = task.catch((): void => undefined);
    await task;
  }
}

class HttpError extends Error {
  readonly statusCode: number;
  constructor(statusCode: number, message: string) {
    super(message);
    this.statusCode = statusCode;
  }
}

const DECISIONS = new Set<MasterDecisionAction>([
  'ACCEPT',
  'MODIFY',
  'RESEARCH_MORE',
  'OVERRIDE',
  'REJECT',
]);

export class MissionControlServer {
  private readonly config: Required<Omit<MissionControlServerConfig, 'executor'>> & { executor: MissionExecutor };
  private readonly store: MissionStore;
  private server: Server | null = null;

  constructor(config: MissionControlServerConfig) {
    const token = config.token.trim();
    if (token.length < 20) throw new Error('Mission Control token must contain at least 20 characters.');
    this.config = {
      token,
      dataPath: config.dataPath,
      host: config.host ?? '127.0.0.1',
      port: config.port ?? 8787,
      canonicalRuntime: config.canonicalRuntime ?? 'NEXUS-1000',
      superBrainVersion: config.superBrainVersion ?? 'unknown',
      apiVersion: config.apiVersion ?? '1',
      capabilities: config.capabilities ?? [],
      executor: config.executor ?? new UnavailableMissionExecutor(),
      maxBodyBytes: config.maxBodyBytes ?? 64 * 1024,
    };
    this.store = new MissionStore(this.config.dataPath);
  }

  async listen(): Promise<MissionControlAddress> {
    if (this.server) throw new Error('Mission Control server is already running.');
    this.server = createServer((request, response): void => {
      void this.handle(request, response).catch((error: unknown): void => {
        if (response.headersSent) {
          response.destroy();
          return;
        }
        const statusCode = error instanceof HttpError ? error.statusCode : 500;
        const detail = error instanceof HttpError ? error.message : 'Unexpected Mission Control error.';
        this.sendJson(response, statusCode, { error: statusCode === 500 ? 'internal_error' : 'request_failed', detail });
      });
    });

    await new Promise<void>((resolve, reject): void => {
      const server = this.server;
      if (!server) {
        reject(new Error('Mission Control server was not created.'));
        return;
      }
      server.once('error', reject);
      server.listen(this.config.port, this.config.host, (): void => {
        server.off('error', reject);
        resolve();
      });
    });

    const address = this.server.address();
    if (!address || typeof address === 'string') throw new Error('Mission Control did not expose a TCP address.');
    const host = this.config.host;
    return { host, port: address.port, url: `http://${host}:${address.port}` };
  }

  async close(): Promise<void> {
    const server = this.server;
    this.server = null;
    if (!server) return;
    await new Promise<void>((resolve, reject): void => {
      server.close((error?: Error): void => {
        if (error) reject(error);
        else resolve();
      });
    });
  }

  private async handle(request: IncomingMessage, response: ServerResponse): Promise<void> {
    this.setSecurityHeaders(response);
    if (!this.isAuthorized(request.headers.authorization)) {
      this.sendJson(response, 401, { error: 'unauthorized', detail: 'A valid bearer token is required.' });
      return;
    }

    const method = request.method ?? 'GET';
    const url = new URL(request.url ?? '/', 'http://mission-control.local');

    if (method === 'GET' && url.pathname === '/api/system/status') {
      const executorStatus = await this.config.executor.getStatus();
      this.sendJson(response, 200, {
        canonicalRuntime: this.config.canonicalRuntime,
        interactiveMissionsAvailable: executorStatus.interactiveMissionsAvailable,
        researchMissionsAvailable: executorStatus.researchMissionsAvailable,
        configuredProviders: executorStatus.configuredProviders,
        superBrainVersion: this.config.superBrainVersion,
        apiVersion: this.config.apiVersion,
        capabilities: this.config.capabilities,
      });
      return;
    }

    if (method === 'GET' && url.pathname === '/api/missions') {
      this.sendJson(response, 200, { missions: await this.store.list() });
      return;
    }

    if (method === 'POST' && (url.pathname === '/api/missions/ask' || url.pathname === '/api/missions/research')) {
      const mode: MissionMode = url.pathname.endsWith('/research') ? 'research' : 'ask';
      await this.startMission(request, response, mode);
      return;
    }

    const decisionMatch = url.pathname.match(/^\/api\/missions\/([^/]+)\/master-decision$/);
    if (method === 'POST' && decisionMatch) {
      const runId = this.decodeRunId(decisionMatch[1]);
      await this.recordMasterDecision(request, response, runId);
      return;
    }

    const detailMatch = url.pathname.match(/^\/api\/missions\/([^/]+)$/);
    if (method === 'GET' && detailMatch) {
      const runId = this.decodeRunId(detailMatch[1]);
      const detail = await this.store.get(runId);
      if (!detail) throw new HttpError(404, 'Mission was not found.');
      this.sendJson(response, 200, {
        run: detail.run,
        evidence: detail.evidence,
        audit: detail.audit,
        masterDecisions: detail.masterDecisions,
      });
      return;
    }

    this.sendJson(response, 404, { error: 'not_found', detail: 'Route was not found.' });
  }

  private async startMission(request: IncomingMessage, response: ServerResponse, mode: MissionMode): Promise<void> {
    const status = await this.config.executor.getStatus();
    const available = mode === 'research'
      ? status.researchMissionsAvailable
      : status.interactiveMissionsAvailable;
    if (!available) {
      throw new HttpError(503, `${mode === 'research' ? 'Research' : 'Interactive'} mission execution is not configured.`);
    }

    const body = await this.readJsonBody(request);
    const question = typeof body.mission === 'string' ? body.mission.trim() : '';
    if (!question) throw new HttpError(400, 'mission must be a non-empty string.');
    if (question.length > 20_000) throw new HttpError(413, 'mission is too large.');

    const runId = randomUUID();
    const createdAt = new Date().toISOString();
    const initial: StoredMission = {
      run: { runId, question, status: 'running', createdAt },
      evidence: [],
      audit: [{ stage: 'mission_received', detail: `${mode} mission accepted by Mission Control.` }],
      masterDecisions: [],
    };
    await this.store.upsert(initial);

    try {
      const result = await this.config.executor.execute({ runId, question, mode });
      const finalValue = result.nexusFinalValue.trim();
      if (!finalValue) throw new Error('Mission executor returned an empty NEXUS final value.');

      const missionResponse: MissionResponse = {
        runId,
        nexusFinalValue: finalValue,
        ...(result.verificationNote ? { verificationNote: result.verificationNote } : {}),
        ...(result.draftResponses ? { draftResponses: result.draftResponses } : {}),
      };
      const completed: StoredMission = {
        run: { ...initial.run, status: 'completed', finalValue },
        evidence: result.evidence,
        audit: [
          ...result.audit,
          { stage: 'mission_completed', detail: 'Mission executor returned a completed result.' },
        ],
        masterDecisions: [],
        response: missionResponse,
      };
      await this.store.finalize(completed);
      this.sendJson(response, 200, missionResponse);
    } catch {
      const failed: StoredMission = {
        ...initial,
        run: { ...initial.run, status: 'failed' },
        audit: [{ stage: 'mission_failed', detail: 'Mission executor failed closed.' }],
      };
      await this.store.finalize(failed);
      throw new HttpError(503, 'Mission execution failed closed. No NEXUS approval was produced.');
    }
  }

  private async recordMasterDecision(
    request: IncomingMessage,
    response: ServerResponse,
    runId: string,
  ): Promise<void> {
    const body = await this.readJsonBody(request);
    const rawAction = typeof body.action === 'string' ? body.action : '';
    if (!DECISIONS.has(rawAction as MasterDecisionAction)) throw new HttpError(400, 'Invalid master decision action.');
    const note = typeof body.note === 'string' ? body.note.trim() : '';
    if (note.length > 4_000) throw new HttpError(413, 'Master decision note is too large.');

    const decision: MasterDecisionRecord = {
      action: rawAction as MasterDecisionAction,
      note,
      createdAt: new Date().toISOString(),
    };
    const updated = await this.store.addDecision(runId, decision);
    if (!updated) throw new HttpError(404, 'Mission was not found.');
    this.sendJson(response, 200, decision);
  }

  private async readJsonBody(request: IncomingMessage): Promise<Record<string, unknown>> {
    const contentType = request.headers['content-type'] ?? '';
    if (!contentType.toLowerCase().startsWith('application/json')) {
      throw new HttpError(415, 'Content-Type must be application/json.');
    }

    const chunks: Buffer[] = [];
    let bytes = 0;
    for await (const chunk of request) {
      const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
      bytes += buffer.length;
      if (bytes > this.config.maxBodyBytes) throw new HttpError(413, 'Request body is too large.');
      chunks.push(buffer);
    }

    if (chunks.length === 0) throw new HttpError(400, 'JSON body is required.');
    try {
      const parsed = JSON.parse(Buffer.concat(chunks).toString('utf8')) as unknown;
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new HttpError(400, 'JSON body must be an object.');
      }
      return parsed as Record<string, unknown>;
    } catch (error) {
      if (error instanceof HttpError) throw error;
      throw new HttpError(400, 'Request body contains invalid JSON.');
    }
  }

  private decodeRunId(encoded: string): string {
    try {
      const decoded = decodeURIComponent(encoded);
      if (!decoded || decoded.includes('/') || decoded.length > 200) throw new Error('invalid');
      return decoded;
    } catch {
      throw new HttpError(400, 'Invalid mission id.');
    }
  }

  private isAuthorized(header: string | undefined): boolean {
    if (!header?.startsWith('Bearer ')) return false;
    const supplied = createHash('sha256').update(header.slice('Bearer '.length)).digest();
    const expected = createHash('sha256').update(this.config.token).digest();
    return timingSafeEqual(supplied, expected);
  }

  private setSecurityHeaders(response: ServerResponse): void {
    response.setHeader('Cache-Control', 'no-store');
    response.setHeader('Content-Security-Policy', "default-src 'none'");
    response.setHeader('Referrer-Policy', 'no-referrer');
    response.setHeader('X-Content-Type-Options', 'nosniff');
  }

  private sendJson(response: ServerResponse, statusCode: number, payload: unknown): void {
    if (response.headersSent) return;
    response.statusCode = statusCode;
    response.setHeader('Content-Type', 'application/json; charset=utf-8');
    response.end(JSON.stringify(payload));
  }
}
