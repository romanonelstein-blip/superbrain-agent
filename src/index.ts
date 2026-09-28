import { AuditLog } from './audit/audit-log.js';
import { CapabilityRegistry } from './core/capability-registry.js';
import { GitProvider } from './core/git.js';
import { GitHubCliProvider } from './core/github.js';
import { NexusBridge } from './core/nexus.js';
import { ApprovalEngine } from './workflow/approval-engine.js';

export { ApprovalEngine, AuditLog, CapabilityRegistry, GitHubCliProvider, GitProvider, NexusBridge };
export * from './types/index.js';
export type {
  NexusBridgeConfig,
  NexusBridgeStatus,
  NexusDecision,
  NexusDecisionRequest,
  NexusDissentInput,
  NexusEvidenceInput,
  NexusStance,
} from './core/nexus.js';

export async function initializeAgent(repositoryPath: string): Promise<void> {
  const git = new GitProvider();
  const github = new GitHubCliProvider();
  const capabilities = new CapabilityRegistry();
  const nexus = new NexusBridge();
  new AuditLog(repositoryPath);

  const repoInfo = await git.getRepositoryInfo(repositoryPath);
  if (!repoInfo) throw new Error(`Invalid Git repository at ${repositoryPath}`);

  const ghStatus = await github.getAuthStatus();
  if (!ghStatus.isAvailable) console.warn('GitHub CLI not available:', ghStatus.error);

  const [caps, nexusStatus] = await Promise.all([
    capabilities.getCapabilities(),
    nexus.getStatus(),
  ]);

  console.log('Available tools:');
  console.log(`Git: ${caps.git.version}`);
  console.log(`GitHub CLI: ${caps.githubCli.available ? caps.githubCli.version : 'Not available'}`);
  console.log(`Ollama: ${caps.ollama.available ? caps.ollama.version : 'Not available'}`);
  console.log(
    `NEXUS-1000: ${nexusStatus.ready ? 'Ready' : nexusStatus.configured ? 'Configured but unavailable' : 'Not configured'}`,
  );
}

export {
  MissionControlServer,
  UnavailableMissionExecutor,
} from './mobile/mission-control.js';
export type {
  MasterDecisionAction,
  MasterDecisionRecord,
  MissionAuditItem,
  MissionControlAddress,
  MissionControlServerConfig,
  MissionDetail,
  MissionDraft,
  MissionEvidence,
  MissionExecutionInput,
  MissionExecutionResult,
  MissionExecutor,
  MissionExecutorStatus,
  MissionMode,
  MissionResponse,
  MissionSummary,
} from './mobile/mission-control.js';

export {
  NexusMissionExecutor,
  UnavailableMissionEvidenceProvider,
} from './mobile/nexus-mission-executor.js';
export type {
  MissionEvidenceBundle,
  MissionEvidenceProvider,
  MissionEvidenceProviderStatus,
  NexusDecisionEngine,
} from './mobile/nexus-mission-executor.js';

export {
  CommandMissionEvidenceProvider,
} from './mobile/command-evidence-provider.js';
export type {
  CommandMissionEvidenceProviderConfig,
} from './mobile/command-evidence-provider.js';

export {
  HttpResearchEvidenceProvider,
} from './mobile/http-research-evidence-provider.js';
export type {
  HttpResearchEvidenceProviderConfig,
  ResearchDiscoveryConfig,
} from './mobile/http-research-evidence-provider.js';

export {
  RealitySentinel,
  predictionContractHash,
} from './core/reality-sentinel.js';
export type {
  PredictionAssumption,
  PredictionContract,
  RealityDriftState,
  RealitySentinelAssessment,
  RealitySentinelAuditItem,
  RealitySentinelConfig,
  RealitySignal,
  RealitySignalDirection,
} from './core/reality-sentinel.js';

export { CrmDataGateway } from './crm/data-gateway.js';
export type {
  CrmDataCapability,
  CrmDataGatewayResponse,
  CrmDataGatewayWeights,
  CrmDataInput,
  CrmDataInputValue,
  CrmDataProvider,
  CrmDataRequest,
  CrmDataResult,
  CrmEvidenceReference,
  CrmGatewayAttempt,
  CrmProviderProfile,
  CrmProviderStatus,
} from './crm/data-gateway.js';

export { FetchJsonHttpTransport } from './crm/http-json-transport.js';
export type {
  JsonHttpMethod,
  JsonHttpQueryValue,
  JsonHttpRequest,
  JsonHttpResponse,
  JsonHttpTransport,
} from './crm/http-json-transport.js';

export { ApolloDataProvider } from './crm/providers/apollo-provider.js';
export type { ApolloDataProviderConfig } from './crm/providers/apollo-provider.js';

export { HunterDataProvider } from './crm/providers/hunter-provider.js';
export type { HunterDataProviderConfig } from './crm/providers/hunter-provider.js';


export {
  NovaProspectsSignalExecutor,
  planNovaProspectsSignal,
} from './crm/novaprospects-signal-planner.js';
export type {
  CrmDataResolver,
  NovaProspectsExecutionItem,
  NovaProspectsExecutionResult,
  NovaProspectsSignal,
  NovaProspectsSignalKind,
  NovaProspectsSignalPlan,
  NovaProspectsSignalPolicy,
  NovaProspectsSignalSubject,
} from './crm/novaprospects-signal-planner.js';


export { ClayDataProvider } from './crm/providers/clay-provider.js';
export type { ClayDataProviderConfig } from './crm/providers/clay-provider.js';


export type { CrmDataGatewayStopReason } from './crm/data-gateway.js';


export type {
  CrmGatewayAttemptAuditEvent,
  CrmGatewayAuditEvent,
  CrmGatewayAuditOptions,
  CrmGatewayAuditSink,
  CrmGatewayStoppedAuditEvent,
} from './crm/gateway-audit.js';

export { FileSignalExecutionStore } from './crm/signal-execution-store.js';
export type { NovaProspectsExecutionStore } from './crm/signal-execution-store.js';
