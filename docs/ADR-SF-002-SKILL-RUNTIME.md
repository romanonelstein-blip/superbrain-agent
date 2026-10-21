# ADR-SF-002: Safe Skill Foundry runtime for SuperBrain

Date: 2026-10-21
Status: implementation candidate; NOT activated in production
Parent PR: #28 (portable skills, intake validator)

## What is implemented

`SkillRuntime` offers a server-side, opt-in registry. The operator registers a trusted, compiled, read-only handler for a pinned SkillCandidate. The skill file itself is metadata/instructions and is **never executed**. `assessSkillCandidate` must return REVIEW-READY, and the pilot permits only the `read-workspace` capability.

The runtime consumes the existing `MissionEvidenceProvider` and `NexusDecisionEngine` interfaces, including the canonical `NexusBridge`. A proposal requires:
- NEXUS core and evidence provider ready;
- cited, hashed, verified observations with independent dissent;
- canonical NEXUS YES, approved, all four true gates, referenced evidence IDs;
- immutable intent digest of workspace, agent, skill content + revision, run, question, evidence and gate results.

No work dispatch occurs at proposal time. Execution then requires an EXACT Master authorization for the same workspace, proposal, intent digest, actor, and a not-expired proof. The provided `HmacSkillMasterVerifier` checks an HMAC-SHA256 proof in constant time and rechecks live workspace Master membership using a required authorization callback. Only a distinct authenticated human approval service may issue signed proofs; the runtime has no signing endpoint. The old Mission Control `ACCEPT` decision endpoint is insufficient: it stores a note but does not authenticate an individual actor or cryptographically bind an action intent. It **cannot** unlock this runtime.

The runtime claims the one-time proposal before any async work, rechecks NEXUS readiness and the Master proof/role before dispatch; all audit append failures block execution. Repeated or concurrent calls cannot dispatch the same plan twice in one process. Handler results are checked against approved evidence IDs.

## Explicit limitations and rollout blocks

1. No production handler, authenticated human proof **issuer**, live Master membership resolver, or durable audit store is wired by default. Production activation requires trusted identity verification, a persistent transactional policy/approval ledger and a distributed idempotency claim. Current process memory is NOT sufficient for serverless/multi-host deployment.
2. The runtime does not grant system permissions. It assumes a developer-reviewed handler truly is read-only. Technical egress isolation, process sandboxing, scoped API permissions and output redaction remain operator responsibilities.
3. An external skill's authorship/license is not attested by the admission validator. REVIEW-READY is structural screening, not an authorization certificate.
4. The canonical Python NEXUS environment may be unavailable. Its `ready=false` gate blocks proposals.
5. The authenticated `GET /api/skills` route lists the optional explicitly registered capabilities; it has **no remote registration, approval or execution path**. Bearer token alone cannot approve a skill.
6. Skill hash, evidence and Master approval expire quickly; no implicit renewals, automatic retries or paid actions.
7. There is no activation in the NovaProspects or Fondio production applications.

## Application integration contract

```ts
// Only inside trusted server-side composition code:
const registry = new SkillRuntime(
  new NexusBridge(),
  evidenceProvider,       // existing verified MissionEvidenceProvider
  masterVerifier,         // HmacSkillMasterVerifier with live role resolver; no permissive default
  durableAuditSink,       // append-only durable store; never best-effort
);
await registry.register({
  agentId: 'research-agent',
  candidate: pinnedAndAuditedCandidate,
  handle: trustedReadOnlyHandler,
});
// Optional MissionControlServer config: skillRegistry: registry
// Before execution, call prepare -> external Master proof -> approve -> execute.
// No client controls a handler or an actor identity.
```

## Acceptance criteria in isolated fixtures

- malformed/elevated skill refused; trusted metadata registered;
- unavailable NEXUS, unverified sources, absent dissent or failed NEIS block preparation;
- no execution before explicit cryptographically verified exact-intent Master authorization;
- expired, modified, wrong-tenant, wrong-plan and replayed proofs block;
- audit outage blocks dispatch;
- authenticated discovery works without an execution endpoint;
- existing mobile, iOS, NEXUS bridge, security scanning and release CI remain green.

## Next steps (separate PR)

Build a PostgreSQL-backed append-only ledger and scoped human actor identity, integrate an authenticated HMAC proof issuer and real-time Master membership resolver, isolate read-only handler network privileges and add E2E tests before enabling any real skill. Do not merge or deploy without a separate gate.
