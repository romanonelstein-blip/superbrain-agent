import type {
  CrmDataCapability,
  CrmDataGatewayStopReason,
  CrmGatewayAttempt,
} from './data-gateway.js';

export interface CrmGatewayAttemptAuditEvent {
  type: 'PROVIDER_ATTEMPT';
  occurredAt: string;
  capability: CrmDataCapability;
  providerId: string;
  state: CrmGatewayAttempt['state'];
}

export interface CrmGatewayStoppedAuditEvent {
  type: 'GATEWAY_STOPPED';
  occurredAt: string;
  capability: CrmDataCapability;
  reason: CrmDataGatewayStopReason;
}

export type CrmGatewayAuditEvent =
  | CrmGatewayAttemptAuditEvent
  | CrmGatewayStoppedAuditEvent;

export interface CrmGatewayAuditSink {
  write(event: CrmGatewayAuditEvent): void | Promise<void>;
}

export interface CrmGatewayAuditOptions {
  sink?: CrmGatewayAuditSink;
  now?: () => Date;
}
