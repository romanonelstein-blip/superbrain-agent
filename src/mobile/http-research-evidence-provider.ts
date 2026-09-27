import { createHash } from 'node:crypto';
import { lookup } from 'node:dns/promises';
import { isIP } from 'node:net';
import type { NexusStance } from '../core/nexus.js';
import type {
  MissionAuditItem,
  MissionExecutionInput,
} from './mission-control.js';
import type {
  MissionEvidenceBundle,
  MissionEvidenceProvider,
  MissionEvidenceProviderStatus,
} from './nexus-mission-executor.js';

export interface ResearchDiscoveryConfig {
  endpoint: string;
  providerName: string;
  bearerToken?: string;
}

export interface HttpResearchEvidenceProviderConfig {
  primary: ResearchDiscoveryConfig;
  dissent: ResearchDiscoveryConfig;
  searchTimeoutMs?: number;
  fetchTimeoutMs?: number;
  maxResultsPerProvider?: number;
  maxSourceBytes?: number;
  maxSearchResponseBytes?: number;
  maxRedirects?: number;
  minimumResearchPrimarySources?: number;
  minimumResearchPrimaryFamilies?: number;
  minimumDissentSources?: number;
  requireDistinctDissentFamily?: boolean;
  allowedSourceHosts?: string[];
  allowPrivateNetworksForTesting?: boolean;
  allowInsecureHttpForTesting?: boolean;
}

interface DiscoveryResult {
  url: string;
  title?: string;
  snippet?: string;
  stance?: NexusStance;
}

interface DiscoveryResponse {
  protocolVersion?: number;
  ready?: boolean;
  results?: DiscoveryResult[];
}

interface DiscoveryRequest {
  protocolVersion: 1;
  type: 'status' | 'search';
  query?: string;
  mode?: string;
  limit?: number;
  requestedStance?: NexusStance;
}

interface RetrievedSource {
  url: string;
  contentType: string;
  text: string;
  contentHash: string;
  bytes: number;
}

const ALLOWED_TEXT_CONTENT_TYPES = [
  'text/html',
  'text/plain',
  'application/json',
  'application/ld+json',
  'application/xml',
  'text/xml',
];

export class HttpResearchEvidenceProvider implements MissionEvidenceProvider {
  private readonly config: Required<Omit<
    HttpResearchEvidenceProviderConfig,
    'allowedSourceHosts' | 'primary' | 'dissent'
  >> & {
    primary: ResearchDiscoveryConfig;
    dissent: ResearchDiscoveryConfig;
    allowedSourceHosts: string[];
  };

  constructor(config: HttpResearchEvidenceProviderConfig) {
    const allowInsecureHttpForTesting = config.allowInsecureHttpForTesting ?? false;
    this.validateDiscoveryConfig(config.primary, 'primary', allowInsecureHttpForTesting);
    this.validateDiscoveryConfig(config.dissent, 'dissent', allowInsecureHttpForTesting);

    if (
      config.primary.endpoint === config.dissent.endpoint
      && config.primary.providerName.trim() === config.dissent.providerName.trim()
    ) {
      throw new Error('Primary and dissent discovery providers must be independently identified.');
    }

    const searchTimeoutMs = config.searchTimeoutMs ?? 15_000;
    const fetchTimeoutMs = config.fetchTimeoutMs ?? 20_000;
    const maxResultsPerProvider = config.maxResultsPerProvider ?? 6;
    const maxSourceBytes = config.maxSourceBytes ?? 512 * 1024;
    const maxSearchResponseBytes = config.maxSearchResponseBytes ?? 256 * 1024;
    const maxRedirects = config.maxRedirects ?? 3;
    const minimumResearchPrimarySources = config.minimumResearchPrimarySources ?? 2;
    const minimumResearchPrimaryFamilies = config.minimumResearchPrimaryFamilies ?? 2;
    const minimumDissentSources = config.minimumDissentSources ?? 1;
    const requireDistinctDissentFamily = config.requireDistinctDissentFamily ?? true;

    this.requireIntegerRange(searchTimeoutMs, 100, 120_000, 'searchTimeoutMs');
    this.requireIntegerRange(fetchTimeoutMs, 100, 120_000, 'fetchTimeoutMs');
    this.requireIntegerRange(maxResultsPerProvider, 1, 20, 'maxResultsPerProvider');
    this.requireIntegerRange(maxSourceBytes, 1024, 5 * 1024 * 1024, 'maxSourceBytes');
    this.requireIntegerRange(maxSearchResponseBytes, 1024, 2 * 1024 * 1024, 'maxSearchResponseBytes');
    this.requireIntegerRange(maxRedirects, 0, 8, 'maxRedirects');
    this.requireIntegerRange(minimumResearchPrimarySources, 1, 10, 'minimumResearchPrimarySources');
    this.requireIntegerRange(minimumResearchPrimaryFamilies, 1, 10, 'minimumResearchPrimaryFamilies');
    this.requireIntegerRange(minimumDissentSources, 1, 10, 'minimumDissentSources');
    if (minimumResearchPrimaryFamilies > minimumResearchPrimarySources) {
      throw new Error('minimumResearchPrimaryFamilies may not exceed minimumResearchPrimarySources.');
    }

    this.config = {
      primary: {
        endpoint: config.primary.endpoint,
        providerName: config.primary.providerName.trim(),
        ...(config.primary.bearerToken ? { bearerToken: config.primary.bearerToken } : {}),
      },
      dissent: {
        endpoint: config.dissent.endpoint,
        providerName: config.dissent.providerName.trim(),
        ...(config.dissent.bearerToken ? { bearerToken: config.dissent.bearerToken } : {}),
      },
      searchTimeoutMs,
      fetchTimeoutMs,
      maxResultsPerProvider,
      maxSourceBytes,
      maxSearchResponseBytes,
      maxRedirects,
      minimumResearchPrimarySources,
      minimumResearchPrimaryFamilies,
      minimumDissentSources,
      requireDistinctDissentFamily,
      allowedSourceHosts: (config.allowedSourceHosts ?? [])
        .map((host): string => host.trim().toLowerCase())
        .filter(Boolean),
      allowPrivateNetworksForTesting: config.allowPrivateNetworksForTesting ?? false,
      allowInsecureHttpForTesting,
    };
  }

  async getStatus(): Promise<MissionEvidenceProviderStatus> {
    try {
      const [primary, dissent] = await Promise.all([
        this.discovery(this.config.primary, { protocolVersion: 1, type: 'status' }),
        this.discovery(this.config.dissent, { protocolVersion: 1, type: 'status' }),
      ]);
      const ready = primary.ready === true && dissent.ready === true;
      return {
        interactiveMissionsAvailable: ready,
        researchMissionsAvailable: ready,
        configuredProviders: ready
          ? [this.config.primary.providerName, this.config.dissent.providerName]
          : [],
      };
    } catch {
      return {
        interactiveMissionsAvailable: false,
        researchMissionsAvailable: false,
        configuredProviders: [],
      };
    }
  }

  async collect(input: MissionExecutionInput): Promise<MissionEvidenceBundle> {
    const [primaryResults, dissentResults] = await Promise.all([
      this.search(this.config.primary, input, 'neutral'),
      this.search(this.config.dissent, input, 'challenge'),
    ]);

    const primaryEvidence = await this.retrieveEvidence(
      primaryResults,
      this.config.primary.providerName,
      'neutral',
    );
    const dissentEvidence = await this.retrieveEvidence(
      dissentResults,
      this.config.dissent.providerName,
      'challenge',
    );

    if (primaryEvidence.length === 0) {
      throw new Error('Primary research provider returned no retrievable evidence.');
    }

    const primaryFamilies = new Set(
      primaryEvidence.map((item): string => item.sourceFamily).filter(Boolean),
    );
    const minimumPrimarySources = input.mode === 'research'
      ? this.config.minimumResearchPrimarySources
      : 1;
    const minimumPrimaryFamilies = input.mode === 'research'
      ? this.config.minimumResearchPrimaryFamilies
      : 1;

    if (primaryEvidence.length < minimumPrimarySources) {
      throw new Error(
        `Research diversity gate requires at least ${minimumPrimarySources} unique primary source(s).`,
      );
    }
    if (primaryFamilies.size < minimumPrimaryFamilies) {
      throw new Error(
        `Research diversity gate requires at least ${minimumPrimaryFamilies} primary source families.`,
      );
    }

    const primaryUrls = new Set(primaryEvidence.map((item): string => item.sourceId));
    const primaryHashes = new Set(
      primaryEvidence.map((item): string => item.contentHash ?? '').filter(Boolean),
    );
    const independentDissentEvidence = dissentEvidence.filter((item): boolean => {
      if (primaryUrls.has(item.sourceId)) return false;
      if (item.contentHash && primaryHashes.has(item.contentHash)) return false;
      if (this.config.requireDistinctDissentFamily && primaryFamilies.has(item.sourceFamily)) {
        return false;
      }
      return true;
    });

    if (independentDissentEvidence.length < this.config.minimumDissentSources) {
      throw new Error(
        `Research diversity gate requires at least ${this.config.minimumDissentSources} independent dissent source(s).`,
      );
    }

    const audit: MissionAuditItem[] = [
      {
        stage: 'research_primary',
        detail:
          `${this.config.primary.providerName}: ${primaryEvidence.length} unique source(s) across ${primaryFamilies.size} source family/families.`,
      },
      {
        stage: 'research_dissent',
        detail:
          `${this.config.dissent.providerName}: ${independentDissentEvidence.length} independent dissent source(s) after overlap filtering.`,
      },
      {
        stage: 'research_diversity_gate',
        detail:
          `PASS primary_sources=${primaryEvidence.length}; primary_families=${primaryFamilies.size}; dissent_sources=${independentDissentEvidence.length}.`,
      },
    ];

    return {
      evidence: primaryEvidence,
      dissent: {
        completed: true,
        provider: this.config.dissent.providerName,
        evidence: independentDissentEvidence,
      },
      audit,
      verificationNote:
        `Research diversity gate passed with ${primaryEvidence.length} primary source(s), ${primaryFamilies.size} primary family/families and ${independentDissentEvidence.length} independent dissent source(s).`,
    };
  }

  private async search(
    provider: ResearchDiscoveryConfig,
    input: MissionExecutionInput,
    requestedStance: NexusStance,
  ): Promise<DiscoveryResult[]> {
    const response = await this.discovery(provider, {
      protocolVersion: 1,
      type: 'search',
      query: input.question,
      mode: input.mode,
      limit: this.config.maxResultsPerProvider,
      requestedStance,
    });

    if (!Array.isArray(response.results)) {
      throw new Error(`${provider.providerName} did not return a results array.`);
    }

    const seen = new Set<string>();
    const results: DiscoveryResult[] = [];
    for (const item of response.results) {
      if (!item || typeof item !== 'object') continue;
      const url = typeof item.url === 'string' ? item.url.trim() : '';
      if (!url || seen.has(url)) continue;
      seen.add(url);
      results.push({
        url,
        ...(typeof item.title === 'string' ? { title: item.title.trim() } : {}),
        ...(typeof item.snippet === 'string' ? { snippet: item.snippet.trim() } : {}),
        ...(item.stance === 'support' || item.stance === 'challenge' || item.stance === 'neutral'
          ? { stance: item.stance }
          : {}),
      });
      if (results.length >= this.config.maxResultsPerProvider) break;
    }
    return results;
  }

  private async discovery(
    provider: ResearchDiscoveryConfig,
    body: DiscoveryRequest,
  ): Promise<DiscoveryResponse> {
    const endpoint = await this.validateNetworkUrl(provider.endpoint, true);
    const controller = new AbortController();
    const timeout = setTimeout((): void => controller.abort(), this.config.searchTimeoutMs);
    try {
      const response = await fetch(endpoint, {
        method: 'POST',
        redirect: 'error',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
          ...(provider.bearerToken
            ? { Authorization: `Bearer ${provider.bearerToken}` }
            : {}),
        },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!response.ok) {
        throw new Error(`${provider.providerName} returned HTTP ${response.status}.`);
      }
      const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
      if (!contentType.includes('application/json')) {
        throw new Error(`${provider.providerName} must return application/json.`);
      }
      const bytes = await this.readLimited(response, this.config.maxSearchResponseBytes);
      let parsed: unknown;
      try {
        parsed = JSON.parse(Buffer.from(bytes).toString('utf8')) as unknown;
      } catch {
        throw new Error(`${provider.providerName} returned invalid JSON.`);
      }
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        throw new Error(`${provider.providerName} returned a non-object response.`);
      }
      const object = parsed as DiscoveryResponse;
      if (object.protocolVersion !== undefined && object.protocolVersion !== 1) {
        throw new Error(`${provider.providerName} returned an unsupported protocol version.`);
      }
      return object;
    } finally {
      clearTimeout(timeout);
    }
  }

  private async retrieveEvidence(
    results: DiscoveryResult[],
    providerName: string,
    defaultStance: NexusStance,
  ): Promise<MissionEvidenceBundle['evidence']> {
    const evidence: MissionEvidenceBundle['evidence'] = [];
    const canonicalUrls = new Set<string>();
    const contentHashes = new Set<string>();

    for (const result of results) {
      try {
        const source = await this.fetchSource(result.url);
        if (canonicalUrls.has(source.url)) continue;
        canonicalUrls.add(source.url);

        if (contentHashes.has(source.contentHash)) continue;
        contentHashes.add(source.contentHash);

        const claim = this.buildGroundedClaim(source);
        if (!claim) continue;

        evidence.push({
          id: `web-${createHash('sha256').update(source.url).digest('hex').slice(0, 20)}`,
          claim,
          stance: result.stance ?? defaultStance,
          sourceId: source.url,
          sourceFamily: new URL(source.url).hostname.toLowerCase(),
          reliability: this.sourceReliability(source),
          freshness: this.sourceFreshness(source),
          relevance: 1,
          verified: true,
          citation: source.url,
          contentHash: source.contentHash,
          retrievedAt: new Date().toISOString(),
          contentType: source.contentType,
          provider: providerName,
        });
      } catch {
        continue;
      }
    }

    return evidence;
  }

  private async fetchSource(initialUrl: string): Promise<RetrievedSource> {
    let current = await this.validateNetworkUrl(initialUrl, false);

    for (let redirects = 0; redirects <= this.config.maxRedirects; redirects += 1) {
      const controller = new AbortController();
      const timeout = setTimeout((): void => controller.abort(), this.config.fetchTimeoutMs);
      try {
        const response = await fetch(current, {
          method: 'GET',
          redirect: 'manual',
          headers: {
            Accept: 'text/html,text/plain,application/json,application/ld+json,application/xml,text/xml;q=0.9,*/*;q=0.1',
            'User-Agent': 'SuperBrain-Research/1.0',
          },
          signal: controller.signal,
        });

        if (response.status >= 300 && response.status < 400) {
          const location = response.headers.get('location');
          if (!location) throw new Error('Source redirect is missing Location.');
          if (redirects >= this.config.maxRedirects) throw new Error('Source exceeded redirect limit.');
          const next = new URL(location, current).toString();
          current = await this.validateNetworkUrl(next, false);
          continue;
        }

        if (!response.ok) throw new Error(`Source returned HTTP ${response.status}.`);

        const contentTypeHeader = response.headers.get('content-type')?.toLowerCase() ?? '';
        const contentType = contentTypeHeader.split(';')[0].trim();
        if (!ALLOWED_TEXT_CONTENT_TYPES.includes(contentType)) {
          throw new Error(`Unsupported source content type: ${contentType || 'unknown'}.`);
        }

        const bytes = await this.readLimited(response, this.config.maxSourceBytes);
        const buffer = Buffer.from(bytes);
        const rawText = buffer.toString('utf8');
        const text = contentType === 'text/html'
          ? this.htmlToText(rawText)
          : rawText.replace(/\s+/g, ' ').trim();

        if (!text) throw new Error('Source contained no usable text.');

        return {
          url: current.toString(),
          contentType,
          text,
          contentHash: `sha256:${createHash('sha256').update(buffer).digest('hex')}`,
          bytes: buffer.byteLength,
        };
      } finally {
        clearTimeout(timeout);
      }
    }

    throw new Error('Source retrieval failed.');
  }

  private buildGroundedClaim(source: RetrievedSource): string {
    // Discovery metadata is intentionally excluded here. Search titles and
    // snippets help us find a URL, but only bytes fetched and hashed by
    // SuperBrain are allowed to become verified claim text.
    return source.text
      .slice(0, 4000)
      .trim();
  }

  private sourceReliability(source: RetrievedSource): number {
    const url = new URL(source.url);
    const protocolScore = url.protocol === 'https:' ? 0.1 : 0;
    const contentScore = source.contentType === 'text/html' || source.contentType === 'text/plain'
      ? 0.8
      : 0.7;
    return Math.min(1, contentScore + protocolScore);
  }

  private sourceFreshness(source: RetrievedSource): number {
    void source;
    // Retrieval time is known, but publication time is not. Do not invent
    // recency. A conservative neutral score keeps NEXUS from treating a
    // freshly fetched old document as freshly published information.
    return 0.5;
  }

  private htmlToText(html: string): string {
    return html
      .replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, ' ')
      .replace(/<style\b[^>]*>[\s\S]*?<\/style>/gi, ' ')
      .replace(/<noscript\b[^>]*>[\s\S]*?<\/noscript>/gi, ' ')
      .replace(/<svg\b[^>]*>[\s\S]*?<\/svg>/gi, ' ')
      .replace(/<!--([\s\S]*?)-->/g, ' ')
      .replace(/<[^>]+>/g, ' ')
      .replace(/&nbsp;/gi, ' ')
      .replace(/&amp;/gi, '&')
      .replace(/&lt;/gi, '<')
      .replace(/&gt;/gi, '>')
      .replace(/&quot;/gi, '"')
      .replace(/&#39;/gi, "'")
      .replace(/\s+/g, ' ')
      .trim();
  }

  private async validateNetworkUrl(value: string, discoveryEndpoint: boolean): Promise<URL> {
    let url: URL;
    try {
      url = new URL(value);
    } catch {
      throw new Error('Research URL is invalid.');
    }
    if (url.username || url.password) throw new Error('Research URLs may not contain credentials.');

    const insecureAllowed = this.config.allowInsecureHttpForTesting && url.protocol === 'http:';
    if (url.protocol !== 'https:' && !insecureAllowed) {
      throw new Error('Research networking requires HTTPS.');
    }

    const hostname = url.hostname.toLowerCase();
    if (!hostname) throw new Error('Research URL is missing a hostname.');

    if (!discoveryEndpoint && this.config.allowedSourceHosts.length > 0) {
      const allowed = this.config.allowedSourceHosts.some((host): boolean =>
        hostname === host || hostname.endsWith(`.${host}`),
      );
      if (!allowed) throw new Error('Source hostname is not on the allowlist.');
    }

    if (!this.config.allowPrivateNetworksForTesting) {
      await this.rejectPrivateHost(hostname);
    }

    return url;
  }

  private async rejectPrivateHost(hostname: string): Promise<void> {
    if (hostname === 'localhost' || hostname.endsWith('.localhost')) {
      throw new Error('Private network hosts are not allowed.');
    }

    if (isIP(hostname)) {
      if (this.isPrivateIp(hostname)) throw new Error('Private network hosts are not allowed.');
      return;
    }

    const addresses = await lookup(hostname, { all: true, verbatim: true });
    if (addresses.length === 0) throw new Error('Research hostname did not resolve.');
    if (addresses.some((entry): boolean => this.isPrivateIp(entry.address))) {
      throw new Error('Research hostname resolves to a private or reserved address.');
    }
  }

  private isPrivateIp(address: string): boolean {
    const version = isIP(address);
    if (version === 4) {
      const parts = address.split('.').map(Number);
      const [a, b] = parts;
      if (a === 0 || a === 10 || a === 127) return true;
      if (a === 100 && b >= 64 && b <= 127) return true;
      if (a === 169 && b === 254) return true;
      if (a === 172 && b >= 16 && b <= 31) return true;
      if (a === 192 && b === 168) return true;
      if (a === 198 && (b === 18 || b === 19)) return true;
      if (a >= 224) return true;
      return false;
    }
    if (version === 6) {
      const normalized = address.toLowerCase();
      if (normalized === '::' || normalized === '::1') return true;
      if (normalized.startsWith('fc') || normalized.startsWith('fd')) return true;
      if (/^fe[89ab]/.test(normalized)) return true;
      if (normalized.startsWith('ff')) return true;
      if (normalized.startsWith('2001:db8')) return true;
      if (normalized.startsWith('::ffff:')) {
        const mapped = normalized.slice('::ffff:'.length);
        return isIP(mapped) === 4 ? this.isPrivateIp(mapped) : true;
      }
      return false;
    }
    return true;
  }

  private async readLimited(response: Response, limit: number): Promise<Uint8Array> {
    if (!response.body) return new Uint8Array();
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let total = 0;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      if (!value) continue;
      total += value.byteLength;
      if (total > limit) {
        await reader.cancel();
        throw new Error('Research response exceeded configured byte limit.');
      }
      chunks.push(value);
    }

    const merged = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) {
      merged.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return merged;
  }

  private validateDiscoveryConfig(
    config: ResearchDiscoveryConfig,
    label: string,
    allowInsecureHttpForTesting: boolean,
  ): void {
    if (!config.endpoint.trim()) throw new Error(`${label} discovery endpoint is required.`);
    if (!config.providerName.trim()) throw new Error(`${label} providerName is required.`);

    let url: URL;
    try {
      url = new URL(config.endpoint);
    } catch {
      throw new Error(`${label} discovery endpoint is invalid.`);
    }
    if (url.username || url.password) {
      throw new Error(`${label} discovery endpoint may not contain credentials.`);
    }
    if (url.protocol !== 'https:' && !(allowInsecureHttpForTesting && url.protocol === 'http:')) {
      throw new Error(`${label} discovery endpoint requires HTTPS.`);
    }
  }

  private requireIntegerRange(value: number, minimum: number, maximum: number, field: string): void {
    if (!Number.isInteger(value) || value < minimum || value > maximum) {
      throw new Error(`${field} must be an integer between ${minimum} and ${maximum}.`);
    }
  }
}
