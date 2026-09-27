# Evidence Provider Protocol

SuperBrain Mission Control can connect an external evidence collector to
`NexusMissionExecutor` without giving that collector authority to approve a
mission. The collector only supplies evidence, dissent, drafts and audit
context. NEXUS remains the decision boundary.

The adapter executes the configured command directly with `shell: false`.
It writes exactly one JSON request to stdin and requires exactly one JSON
object on stdout. Extra logs on stdout make the request invalid. Diagnostic
logs should go to stderr.

## Configure

Set these environment variables locally or in your deployment secret store:

- `SUPERBRAIN_EVIDENCE_PROVIDER_COMMAND` — executable to run
- `SUPERBRAIN_EVIDENCE_PROVIDER_ARGS` — optional JSON array of arguments
- `SUPERBRAIN_EVIDENCE_PROVIDER_NAME` — optional display name
- `SUPERBRAIN_EVIDENCE_PROVIDER_TIMEOUT_MS` — optional timeout, default 60000

Never commit credentials or provider secrets.

## Protocol version 1

Status request:

```json
{"protocolVersion":1,"type":"status"}
```

Status response:

```json
{
  "protocolVersion": 1,
  "ready": true,
  "interactiveMissionsAvailable": true,
  "researchMissionsAvailable": true,
  "configuredProviders": ["provider-a", "provider-b"]
}
```

Collection request:

```json
{
  "protocolVersion": 1,
  "type": "collect",
  "runId": "uuid",
  "question": "mission text",
  "mode": "research"
}
```

Collection response:

```json
{
  "protocolVersion": 1,
  "evidence": [
    {
      "id": "e1",
      "claim": "A sourced claim",
      "stance": "support",
      "sourceId": "source-1",
      "sourceFamily": "web",
      "reliability": 0.9,
      "freshness": 0.8,
      "relevance": 1,
      "verified": true,
      "citation": "https://example.test/source",
      "contentHash": "sha256:..."
    }
  ],
  "dissent": {
    "completed": true,
    "provider": "independent-provider",
    "requestId": "request-2",
    "evidence": []
  },
  "draftResponses": [
    {"agent":"provider-a","text":"Draft answer","verified":false}
  ],
  "audit": [
    {"stage":"retrieval","detail":"Collected two independent source families."}
  ],
  "verificationNote": "Evidence collection completed."
}
```

## Validation and fail-closed rules

- evidence arrays are required for collection and may not be empty;
- every item requires `id`, `claim`, `sourceId` and `sourceFamily`;
- verified evidence requires both `citation` and `contentHash`;
- scores must be finite numbers from 0 through 1;
- stance must be `support`, `challenge` or `neutral`;
- dissent must have `completed: true` and its evidence is validated by the
  same rules;
- malformed, oversized, timed-out or ambiguous provider output is rejected;
- provider failure never creates a NEXUS approval.

This protocol intentionally separates evidence collection from decision
authority. A provider cannot make Mission Control return mobile `YES`
without NEXUS approving all required canonical gates.
