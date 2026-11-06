import { createHash } from 'node:crypto';

// Admission reviews metadata and text only. It never fetches, installs or executes a skill.
// A passing review is NOT permission to call tools or perform external actions.

export type SkillCapability =
  | 'read-workspace'
  | 'read-network'
  | 'write-workspace'
  | 'external-write'
  | 'execute-script'
  | 'read-secrets'
  | 'paid-api';

export type SkillAdmissionState = 'rejected' | 'quarantined' | 'review-ready';

export interface SkillCandidate {
  directoryName: string;
  skillMarkdown: string;
  sourceUrl: string;
  sourceRevision: string;
  expectedSha256: string;
  requestedCapabilities: readonly string[];
}

export interface SkillManifest {
  name: string;
  description: string;
}

export interface SkillAdmissionResult {
  state: SkillAdmissionState;
  manifest: SkillManifest | null;
  contentSha256: string;
  issues: string[];
  requestedCapabilities: readonly string[];
  approvedForExecution: false;
}

const KNOWN_CAPABILITIES = new Set<SkillCapability>([
  'read-workspace',
  'read-network',
  'write-workspace',
  'external-write',
  'execute-script',
  'read-secrets',
  'paid-api',
]);

const ELEVATED_CAPABILITIES = new Set<SkillCapability>([
  'write-workspace',
  'external-write',
  'execute-script',
  'read-secrets',
  'paid-api',
]);

const SUSPICIOUS_DIRECTIVES: Array<{ code: string; expression: RegExp }> = [
  { code: 'instruction-override', expression: /ignore (?:all |the )?(?:previous|prior|system|developer) instructions/i },
  { code: 'authority-override', expression: /override (?:the )?(?:system|developer|safety) (?:prompt|policy|rules)/i },
  { code: 'secret-exfiltration', expression: /(?:send|upload|export|exfiltrate) (?:the |all )?(?:api keys|credentials|tokens|\.env|private keys)/i },
  { code: 'remote-pipe-execution', expression: /(?:curl|wget)\s+[^\n|]{1,400}\|\s*(?:ba)?sh\b/i },
  { code: 'audit-disable', expression: /(?:disable|delete|bypass) (?:all |the )?(?:audit logs|audit trail|security logging)/i },
];

const NAME_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const SHA256_PATTERN = /^[a-f0-9]{64}$/i;
const REVISION_PATTERN = /^[a-f0-9]{40}$/i;

function scalar(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed || /^[|>{\[]/.test(trimmed)) return null;
  if (trimmed.startsWith('"')) {
    try {
      const value: unknown = JSON.parse(trimmed);
      return typeof value === 'string' ? value : null;
    } catch {
      return null;
    }
  }
  if (trimmed.startsWith("'")) {
    if (!trimmed.endsWith("'") || trimmed.length < 2) return null;
    return trimmed.slice(1, -1).replace(/''/g, "'");
  }
  if (trimmed.includes(' #')) return trimmed.split(' #')[0]?.trim() || null;
  return trimmed;
}

export function parseSkillManifest(markdown: string, directoryName: string): SkillManifest {
  const normalized = markdown.replace(/\r\n/g, '\n');
  if (Buffer.byteLength(normalized, 'utf8') > 128 * 1024) {
    throw new Error('skill-too-large');
  }
  if (normalized.split('\n').length > 500) {
    throw new Error('skill-too-many-lines');
  }
  if (!normalized.startsWith('---\n')) {
    throw new Error('missing-frontmatter');
  }
  const end = normalized.indexOf('\n---\n', 4);
  if (end === -1) throw new Error('invalid-frontmatter-boundary');
  const frontmatter = normalized.slice(4, end);
  const entries = new Map<string, string>();
  for (const line of frontmatter.split('\n')) {
    if (!line.trim() || line.trim().startsWith('#')) continue;
    const match = /^([a-z][a-z0-9-]*):\s*(.*)$/.exec(line);
    if (!match) throw new Error('unsupported-frontmatter');
    const key = match[1];
    const value = match[2];
    if (!key || value === undefined || entries.has(key)) {
      throw new Error('duplicate-or-invalid-frontmatter');
    }
    const parsed = scalar(value);
    if (parsed === null) throw new Error('unsupported-frontmatter-value');
    entries.set(key, parsed);
  }
  const name = entries.get('name') ?? '';
  const description = entries.get('description') ?? '';
  if (!NAME_PATTERN.test(name) || name.length > 64 || name !== directoryName) {
    throw new Error('invalid-skill-name');
  }
  if (!description || description.length > 1024) {
    throw new Error('invalid-skill-description');
  }
  return { name, description };
}

function validHttpsSource(candidate: SkillCandidate): boolean {
  try {
    const parsed = new URL(candidate.sourceUrl);
    return (
      parsed.protocol === 'https:' &&
      !parsed.username &&
      !parsed.password &&
      !/^(?:localhost|127\.|0\.|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.|\[?::1\]?)/i.test(parsed.hostname) &&
      !parsed.hostname.endsWith('.local')
    );
  } catch {
    return false;
  }
}

export function assessSkillCandidate(candidate: SkillCandidate): SkillAdmissionResult {
  const issues: string[] = [];
  const contentSha256 = createHash('sha256').update(candidate.skillMarkdown, 'utf8').digest('hex');
  let manifest: SkillManifest | null = null;

  try {
    manifest = parseSkillManifest(candidate.skillMarkdown, candidate.directoryName);
  } catch (error) {
    issues.push(error instanceof Error ? error.message : 'manifest-invalid');
  }
  if (!validHttpsSource(candidate)) issues.push('unsafe-or-invalid-source-url');
  if (!REVISION_PATTERN.test(candidate.sourceRevision)) issues.push('missing-immutable-source-revision');
  if (!SHA256_PATTERN.test(candidate.expectedSha256) || candidate.expectedSha256.toLowerCase() !== contentSha256) {
    issues.push('content-hash-mismatch');
  }

  const capabilities = [...new Set(candidate.requestedCapabilities)];
  for (const capability of capabilities) {
    if (!KNOWN_CAPABILITIES.has(capability as SkillCapability)) {
      issues.push('unknown-capability:' + capability);
    } else if (ELEVATED_CAPABILITIES.has(capability as SkillCapability)) {
      issues.push('elevated-capability:' + capability);
    }
  }
  for (const rule of SUSPICIOUS_DIRECTIVES) {
    if (rule.expression.test(candidate.skillMarkdown)) issues.push('suspicious-directive:' + rule.code);
  }

  const structural = issues.some(issue =>
    ['unsafe-or-invalid-source-url', 'missing-immutable-source-revision', 'content-hash-mismatch'].includes(issue) ||
    issue.startsWith('invalid-') || issue.startsWith('missing-') || issue.startsWith('unsupported-') ||
    issue === 'duplicate-or-invalid-frontmatter' || issue.startsWith('skill-')
  );
  const state: SkillAdmissionState = structural ? 'rejected' : issues.length ? 'quarantined' : 'review-ready';
  return {
    state,
    manifest,
    contentSha256,
    issues,
    requestedCapabilities: capabilities,
    approvedForExecution: false,
  };
}
