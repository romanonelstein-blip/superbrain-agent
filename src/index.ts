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
