import type {
  CrmDataGatewayResponse,
  CrmDataRequest,
  CrmDataGateway,
} from './data-gateway.js';

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

function companyEnrichment(domain: string): CrmDataRequest {
  return {
    capability: 'COMPANY_ENRICHMENT',
    input: { domain },
  };
}

function personEnrichment(email: string): CrmDataRequest {
  return {
    capability: 'PERSON_ENRICHMENT',
    input: { email },
  };
}

function emailVerification(email: string): CrmDataRequest {
  return {
    capability: 'EMAIL_VERIFY',
    input: { email },
  };
}

function emailDiscovery(
  firstName: string,
  lastName: string,
  domain: string,
): CrmDataRequest {
  return {
    capability: 'EMAIL_FIND',
    input: {
      first_name: firstName,
      last_name: lastName,
      domain,
    },
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

  const email = normalized(signal.subject.email);
  const firstName = normalized(signal.subject.firstName);
  const lastName = normalized(signal.subject.lastName);
  const companyDomain = normalized(signal.subject.companyDomain);
  const requests: CrmDataRequest[] = [];

  switch (signal.kind) {
    case 'COMPANY_REFRESH':
      if (companyDomain) requests.push(companyEnrichment(companyDomain));
      break;

    case 'EMAIL_VERIFICATION_REQUIRED':
      if (email) requests.push(emailVerification(email));
      break;

    case 'CONTACT_REFRESH':
      if (email) {
        requests.push(personEnrichment(email), emailVerification(email));
      } else if (
        signal.policy.allowEmailDiscovery
        && firstName
        && lastName
        && companyDomain
      ) {
        requests.push(emailDiscovery(firstName, lastName, companyDomain));
      }
      break;

    case 'PROSPECT_DISCOVERED':
      if (companyDomain) requests.push(companyEnrichment(companyDomain));

      if (email) {
        requests.push(personEnrichment(email), emailVerification(email));
      } else if (
        signal.policy.allowEmailDiscovery
        && firstName
        && lastName
        && companyDomain
      ) {
        requests.push(emailDiscovery(firstName, lastName, companyDomain));
      }
      break;
  }

  return {
    signalId: signal.signalId,
    tenantId: signal.tenantId,
    prospectId: signal.prospectId,
    requests,
  };
}

export class NovaProspectsSignalExecutor {
  constructor(private readonly gateway: CrmDataResolver | CrmDataGateway) {}

  async execute(plan: NovaProspectsSignalPlan): Promise<NovaProspectsExecutionResult> {
    const items: NovaProspectsExecutionItem[] = [];

    for (const request of plan.requests) {
      const response = await this.gateway.resolve(request);
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
