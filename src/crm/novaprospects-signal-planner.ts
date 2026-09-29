import type {
  CrmDataGateway,
  CrmDataGatewayResponse,
  CrmDataRequest,
} from './data-gateway.js';
import type { NovaProspectsExecutionStore } from './signal-execution-store.js';

export type NovaProspectsSignalKind =
  | 'PROSPECT_DISCOVERED'
  | 'CONTACT_REFRESH'
  | 'EMAIL_VERIFICATION_REQUIRED'
  | 'COMPANY_REFRESH';

export interface NovaProspectsSignalSubject {
  email?: string;
  firstName?: string;
  lastName?: string;
  companyDomain?: string;
}

export interface NovaProspectsSignalPolicy {
  allowExternalEnrichment: boolean;
  allowEmailDiscovery: boolean;
  allowedProviders?: readonly string[];
  preferredProviders?: readonly string[];
  /** Total provider executions across all capabilities in this signal. */
  maxProviderAttempts?: number;
}

export interface NovaProspectsSignal {
  signalId: string;
  tenantId: string;
  prospectId: string;
  kind: NovaProspectsSignalKind;
  occurredAt: string;
  subject: NovaProspectsSignalSubject;
  policy: NovaProspectsSignalPolicy;
}

export interface NovaProspectsSignalPlan {
  signalId: string;
  tenantId: string;
  prospectId: string;
  requests: readonly CrmDataRequest[];
  /** Shared execution budget; omitted for legacy, unlimited plans. */
  maxProviderAttempts?: number;
}

export interface NovaProspectsExecutionItem {
  capability: CrmDataRequest['capability'];
  response: CrmDataGatewayResponse;
}

export interface NovaProspectsExecutionResult {
  signalId: string;
  tenantId: string;
  prospectId: string;
  items: readonly NovaProspectsExecutionItem[];
  stoppedReason?: 'SIGNAL_ALREADY_CLAIMED' | 'SIGNAL_STORE_UNAVAILABLE';
}

export interface CrmDataResolver {
  resolve(request: CrmDataRequest): Promise<CrmDataGatewayResponse>;
}

function requireNonEmpty(name: string, value: string): void {
  if (value.trim().length === 0) {
    throw new Error(`${name} must not be empty`);
  }
}

function normalized(value: string | undefined): string | undefined {
  const trimmed = value?.trim();
  return trimmed && trimmed.length > 0 ? trimmed : undefined;
}

function providerPolicy(
  policy: NovaProspectsSignalPolicy,
): Pick<CrmDataRequest, 'allowedProviders' | 'preferredProviders' | 'maxProviderAttempts'> {
  if (
    policy.maxProviderAttempts !== undefined
    && (!Number.isInteger(policy.maxProviderAttempts) || policy.maxProviderAttempts < 1)
  ) {
    throw new Error('maxProviderAttempts must be a positive integer');
  }

  return {
    ...(policy.allowedProviders !== undefined
      ? { allowedProviders: [...policy.allowedProviders] }
      : {}),
    ...(policy.preferredProviders !== undefined
      ? { preferredProviders: [...policy.preferredProviders] }
      : {}),
    ...(policy.maxProviderAttempts !== undefined
      ? { maxProviderAttempts: policy.maxProviderAttempts }
      : {}),
  };
}

function companyEnrichment(
  domain: string,
  policy: ReturnType<typeof providerPolicy>,
): CrmDataRequest {
  return {
    capability: 'COMPANY_ENRICHMENT',
    input: { domain },
    ...policy,
  };
}

function personEnrichment(
  email: string,
  policy: ReturnType<typeof providerPolicy>,
): CrmDataRequest {
  return {
    capability: 'PERSON_ENRICHMENT',
    input: { email },
    ...policy,
  };
}

function emailVerification(
  email: string,
  policy: ReturnType<typeof providerPolicy>,
): CrmDataRequest {
  return {
    capability: 'EMAIL_VERIFY',
    input: { email },
    ...policy,
  };
}

function emailDiscovery(
  firstName: string,
  lastName: string,
  domain: string,
  policy: ReturnType<typeof providerPolicy>,
): CrmDataRequest {
  return {
    capability: 'EMAIL_FIND',
    input: {
      first_name: firstName,
      last_name: lastName,
      domain,
    },
    ...policy,
  };
}

export function planNovaProspectsSignal(signal: NovaProspectsSignal): NovaProspectsSignalPlan {
  requireNonEmpty('signalId', signal.signalId);
  requireNonEmpty('tenantId', signal.tenantId);
  requireNonEmpty('prospectId', signal.prospectId);

  if (!signal.policy.allowExternalEnrichment) {
    return {
      signalId: signal.signalId,
      tenantId: signal.tenantId,
      prospectId: signal.prospectId,
      requests: [],
    };
  }

  const executionPolicy = providerPolicy(signal.policy);
  const email = normalized(signal.subject.email);
  const firstName = normalized(signal.subject.firstName);
  const lastName = normalized(signal.subject.lastName);
  const companyDomain = normalized(signal.subject.companyDomain);
  const requests: CrmDataRequest[] = [];

  switch (signal.kind) {
    case 'COMPANY_REFRESH':
      if (companyDomain) requests.push(companyEnrichment(companyDomain, executionPolicy));
      break;

    case 'EMAIL_VERIFICATION_REQUIRED':
      if (email) requests.push(emailVerification(email, executionPolicy));
      break;

    case 'CONTACT_REFRESH':
      if (email) {
        requests.push(
          personEnrichment(email, executionPolicy),
          emailVerification(email, executionPolicy),
        );
      } else if (
        signal.policy.allowEmailDiscovery
        && firstName
        && lastName
        && companyDomain
      ) {
        requests.push(
          emailDiscovery(firstName, lastName, companyDomain, executionPolicy),
        );
      }
      break;

    case 'PROSPECT_DISCOVERED':
      if (companyDomain) {
        requests.push(companyEnrichment(companyDomain, executionPolicy));
      }

      if (email) {
        requests.push(
          personEnrichment(email, executionPolicy),
          emailVerification(email, executionPolicy),
        );
      } else if (
        signal.policy.allowEmailDiscovery
        && firstName
        && lastName
        && companyDomain
      ) {
        requests.push(
          emailDiscovery(firstName, lastName, companyDomain, executionPolicy),
        );
      }
      break;
  }

  return {
    signalId: signal.signalId,
    tenantId: signal.tenantId,
    prospectId: signal.prospectId,
    requests,
    ...(executionPolicy.maxProviderAttempts !== undefined
      ? { maxProviderAttempts: executionPolicy.maxProviderAttempts }
      : {}),
  };
}

export class NovaProspectsSignalExecutor {
  constructor(
    private readonly gateway: CrmDataResolver | CrmDataGateway,
    private readonly executionStore?: NovaProspectsExecutionStore,
  ) {}

  async execute(plan: NovaProspectsSignalPlan): Promise<NovaProspectsExecutionResult> {
    requireNonEmpty('signalId', plan.signalId);
    requireNonEmpty('tenantId', plan.tenantId);
    requireNonEmpty('prospectId', plan.prospectId);
    if (
      plan.maxProviderAttempts !== undefined
      && (!Number.isSafeInteger(plan.maxProviderAttempts) || plan.maxProviderAttempts < 1)
    ) {
      throw new Error('maxProviderAttempts must be a positive safe integer');
    }

    const items: NovaProspectsExecutionItem[] = [];
    let remainingAttempts = plan.maxProviderAttempts;

    if (this.executionStore && plan.requests.length > 0) {
      let claimed = false;
      let stoppedReason: NovaProspectsExecutionResult['stoppedReason'] = 'SIGNAL_ALREADY_CLAIMED';
      try {
        claimed = await this.executionStore.claim(plan.tenantId, plan.signalId) === 'CLAIMED';
      } catch {
        // Store failures may include private paths or credentials. Do not leak
        // them, and never run paid providers without a confirmed reservation.
        stoppedReason = 'SIGNAL_STORE_UNAVAILABLE';
      }
      if (!claimed) {
        return {
          signalId: plan.signalId, tenantId: plan.tenantId, prospectId: plan.prospectId,
          items, stoppedReason,
        };
      }
    }

    for (const request of plan.requests) {
      if (remainingAttempts === 0) {
        items.push({
          capability: request.capability,
          response: { result: null, attempts: [], stoppedReason: 'MAX_PROVIDER_ATTEMPTS' },
        });
        continue;
      }

      const response = await this.gateway.resolve(remainingAttempts === undefined
        ? request
        : {
          ...request,
          maxProviderAttempts: Math.min(
            request.maxProviderAttempts ?? remainingAttempts,
            remainingAttempts,
          ),
        });
      if (remainingAttempts !== undefined) {
        // Unavailable providers were never executed. Errors and misses can still
        // incur charges, so they consume the same budget as successful calls.
        remainingAttempts = Math.max(0, remainingAttempts
          - response.attempts.filter((attempt) => attempt.state !== 'UNAVAILABLE').length);
      }
      items.push({
        capability: request.capability,
        response,
      });
    }

    return {
      signalId: plan.signalId,
      tenantId: plan.tenantId,
      prospectId: plan.prospectId,
      items,
    };
  }
}
