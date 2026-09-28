export type CrmDataCapability =
  | 'PERSON_SEARCH'
  | 'COMPANY_SEARCH'
  | 'PERSON_ENRICHMENT'
  | 'COMPANY_ENRICHMENT'
  | 'EMAIL_FIND'
  | 'EMAIL_VERIFY';

export type CrmDataInputValue = string | number | boolean | readonly string[] | undefined;
export type CrmDataInput = Readonly<Record<string, CrmDataInputValue>>;

export interface CrmDataRequest {
  capability: CrmDataCapability;
  input: CrmDataInput;
  preferredProviders?: readonly string[];
  allowedProviders?: readonly string[];
  maxProviderAttempts?: number;
}

export interface CrmProviderProfile {
  quality: number;
  costEfficiency: number;
  speed: number;
}

export interface CrmProviderStatus {
  available: boolean;
  reason?: string;
}

export interface CrmEvidenceReference {
  source: string;
  retrievedAt: string;
  externalId?: string;
}

export interface CrmDataResult {
  providerId: string;
  capability: CrmDataCapability;
  outcome: 'FOUND' | 'NOT_FOUND';
  confidence: number;
  data: Readonly<Record<string, unknown>>;
  evidence: readonly CrmEvidenceReference[];
  costUnits?: number;
}

export interface CrmDataProvider {
  id: string;
  capabilities: readonly CrmDataCapability[];
  profile: CrmProviderProfile;
  getStatus(): Promise<CrmProviderStatus>;
  execute(request: CrmDataRequest): Promise<CrmDataResult>;
}

export interface CrmGatewayAttempt {
  providerId: string;
  state: 'UNAVAILABLE' | 'ERROR' | 'NOT_FOUND' | 'FOUND';
}

export type CrmDataGatewayStopReason =
  | 'NO_ALLOWED_PROVIDER'
  | 'MAX_PROVIDER_ATTEMPTS';

export interface CrmDataGatewayResponse {
  result: CrmDataResult | null;
  attempts: readonly CrmGatewayAttempt[];
  stoppedReason?: CrmDataGatewayStopReason;
}

export interface CrmDataGatewayWeights {
  quality: number;
  costEfficiency: number;
  speed: number;
}

const DEFAULT_WEIGHTS: CrmDataGatewayWeights = {
  quality: 0.5,
  costEfficiency: 0.3,
  speed: 0.2,
};

function assertScore(name: string, value: number): void {
  if (!Number.isFinite(value) || value < 0 || value > 100) {
    throw new Error(`${name} must be between 0 and 100`);
  }
}

function validateProfile(provider: CrmDataProvider): void {
  assertScore(`${provider.id}.quality`, provider.profile.quality);
  assertScore(`${provider.id}.costEfficiency`, provider.profile.costEfficiency);
  assertScore(`${provider.id}.speed`, provider.profile.speed);
}

function validateRequestPolicy(request: CrmDataRequest): void {
  if (
    request.maxProviderAttempts !== undefined
    && (!Number.isInteger(request.maxProviderAttempts) || request.maxProviderAttempts < 1)
  ) {
    throw new Error('maxProviderAttempts must be a positive integer');
  }
}

function preferenceBoost(providerId: string, preferredProviders: readonly string[] | undefined): number {
  if (!preferredProviders) return 0;
  const index = preferredProviders.indexOf(providerId);
  return index === -1 ? 0 : (preferredProviders.length - index) * 1_000;
}

function isAllowed(providerId: string, allowedProviders: readonly string[] | undefined): boolean {
  return allowedProviders === undefined || allowedProviders.includes(providerId);
}

export class CrmDataGateway {
  private readonly providers: readonly CrmDataProvider[];
  private readonly weights: CrmDataGatewayWeights;

  constructor(
    providers: readonly CrmDataProvider[],
    weights: CrmDataGatewayWeights = DEFAULT_WEIGHTS,
  ) {
    if (providers.length === 0) throw new Error('At least one CRM data provider is required');
    providers.forEach(validateProfile);
    this.providers = [...providers];
    this.weights = weights;
  }

  async resolve(request: CrmDataRequest): Promise<CrmDataGatewayResponse> {
    validateRequestPolicy(request);

    const capabilityCandidates = this.providers
      .filter((provider) => provider.capabilities.includes(request.capability));

    if (capabilityCandidates.length === 0) {
      throw new Error(`No CRM data provider supports ${request.capability}`);
    }

    const candidates = capabilityCandidates
      .filter((provider) => isAllowed(provider.id, request.allowedProviders))
      .sort((left, right) => this.rank(right, request) - this.rank(left, request));

    if (candidates.length === 0) {
      return {
        result: null,
        attempts: [],
        stoppedReason: 'NO_ALLOWED_PROVIDER',
      };
    }

    const attempts: CrmGatewayAttempt[] = [];
    let providerExecutions = 0;

    for (const provider of candidates) {
      const status = await provider.getStatus();
      if (!status.available) {
        attempts.push({ providerId: provider.id, state: 'UNAVAILABLE' });
        continue;
      }

      if (
        request.maxProviderAttempts !== undefined
        && providerExecutions >= request.maxProviderAttempts
      ) {
        return {
          result: null,
          attempts,
          stoppedReason: 'MAX_PROVIDER_ATTEMPTS',
        };
      }

      providerExecutions += 1;

      try {
        const result = await provider.execute(request);
        if (result.providerId !== provider.id || result.capability !== request.capability) {
          attempts.push({ providerId: provider.id, state: 'ERROR' });
          continue;
        }

        if (result.outcome === 'FOUND') {
          attempts.push({ providerId: provider.id, state: 'FOUND' });
          return { result, attempts };
        }

        attempts.push({ providerId: provider.id, state: 'NOT_FOUND' });
      } catch {
        // Deliberately avoid surfacing provider error text here because upstream
        // SDKs can include credential-bearing URLs or headers in exceptions.
        attempts.push({ providerId: provider.id, state: 'ERROR' });
      }
    }

    return { result: null, attempts };
  }

  private rank(provider: CrmDataProvider, request: CrmDataRequest): number {
    return (
      provider.profile.quality * this.weights.quality
      + provider.profile.costEfficiency * this.weights.costEfficiency
      + provider.profile.speed * this.weights.speed
      + preferenceBoost(provider.id, request.preferredProviders)
    );
  }
}
