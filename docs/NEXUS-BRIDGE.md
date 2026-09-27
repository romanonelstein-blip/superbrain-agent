# NEXUS-1000 / NEIS bridge

The TypeScript GitHub agent can delegate decision evaluation to the existing Python NEXUS-1000 runtime. It does not create a second orchestrator and it does not grant operational approval by itself.

## Configuration

Set `SUPERBRAIN_NEXUS_ROOT` to the extracted SuperBrain runtime that contains:

- `nexus1000/orchestrator.py`
- `nexus1000/neis.py`

On Windows, the default Python command is `python`. Override it with `SUPERBRAIN_PYTHON` when needed.

## Safety contract

`NexusBridge.evaluate()` is fail-closed. A result is exposed as `approved: true` only when the canonical NEXUS result is `YES` and all four gates are literal `true`:

- Grand Council
- NEIS
- Blinded Dissent
- Verifier

Verified evidence must include a citation and content hash. Runner failures, timeouts, malformed JSON, missing gates, missing core files, and unconfigured paths never become approvals. Raw subprocess errors are not returned, reducing the chance of leaking credentials or provider output.

Blinded dissent is explicit. If an independent dissent/review pass has actually completed, provide a `dissent` object with `completed: true`, a non-empty provider identity, and any counterevidence it produced. If dissent is omitted, the canonical NEXUS runtime keeps the `blinded_dissent` gate closed. The bridge never fabricates a dissent pass from the primary model response.

The bridge only evaluates. It does not push, merge, deploy, publish, change permissions, or auto-apply improvements. Existing approval requirements remain in force.

## Example

```ts
import { NexusBridge } from 'superbrain-agent';

const nexus = new NexusBridge();
const result = await nexus.evaluate({
  question: 'Should this validated change proceed?',
  evidence: [
    {
      id: 'ci:tests',
      claim: 'Regression tests passed',
      sourceId: 'github-actions-run',
      sourceFamily: 'ci',
      verified: true,
      citation: 'All required regression tests passed.',
      contentHash: 'sha256:...',
      reliability: 0.98,
    },
  ],
  dissent: {
    completed: true,
    provider: 'independent-review',
    evidence: [],
  },
});

if (!result.approved) {
  // Stop or request more evidence. Never infer approval from model text.
}
```

A missing blinded-dissent provider remains a failed gate in the canonical NEXUS runtime, so ordinary evidence alone cannot silently manufacture a YES.
