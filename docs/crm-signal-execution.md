# CRM signal execution safety

`maxProviderAttempts` on a NovaProspects signal limits provider executions across
all planned capabilities. Errors and misses count; unavailable providers do not.
This is an attempt limit, not a monetary credit estimate or monthly tenant quota.

## Enable persistent replay protection

```typescript
import {
  FileSignalExecutionStore,
  NovaProspectsSignalExecutor,
  planNovaProspectsSignal,
} from 'superbrain-agent';

const store = new FileSignalExecutionStore('/var/lib/superbrain/signal-claims');
const executor = new NovaProspectsSignalExecutor(gateway, store);
const result = await executor.execute(planNovaProspectsSignal(signal));
```

The store is optional for compatibility. Callers that omit it do not have replay
protection. Use one persistent directory shared by all workers on the same host.
Supply tenant identity and provider policy from the authenticated server context;
this store is not an authorization layer and cannot trust client-selected tenants.

Before resolving any nonempty plan, the executor atomically reserves its
`(tenantId, signalId)` pair. The same pair cannot execute twice, even if the second
plan changes its prospect or inputs. A later refresh must use a new signal ID.
Separate tenants can use the same signal ID without blocking one another.

| Result | Meaning | Provider calls |
| --- | --- | --- |
| No execution-level stop | Reserved, or replay protection was not configured | Subject to provider policy |
| `SIGNAL_ALREADY_CLAIMED` | The signal was previously reserved, including uncertain or partial execution | None for this invocation |
| `SIGNAL_STORE_UNAVAILABLE` | Reservation could not be confirmed | None |

Existing per-capability stop reasons remain on `items[].response.stoppedReason`.
The two execution-level reasons above are on the top-level result.

## Recovery and storage boundaries

- Claims remain after success, provider failure, process crash, or a partial
  write. They are never automatically released or expired. This provides
  at-most-once execution attempts, not guaranteed completion or exactly-once
  upstream billing.
- An interrupted signal may have completed only some capabilities. Inspect
  provider records before deciding whether to create a replacement signal.
  Do not delete a claim or generate a fresh ID as an automatic retry strategy.
- Files contain only a format version. Filenames hash the tenant/signal pair;
  hashes are pseudonymous identifiers, not anonymization. No raw prospect data,
  provider results or credentials are persisted by this store.
- Keep the directory private and on persistent, trusted local storage. Exclusive
  file creation coordinates local processes; network filesystems, distributed
  hosts and ephemeral serverless disks are not supported by this implementation.
- File content is flushed before provider work, but this is not a guarantee
  against filesystem corruption or machine power loss. Backup/restore must not
  roll the claim store back independently of provider side effects.
- Retention is deliberate: deleting old claims permits replay. Plan disk capacity
  and reconcile retention against signal replay windows before pruning.

For multiple hosts, implement `NovaProspectsExecutionStore.claim` with a shared
transactional store and an atomic unique tenant/signal constraint. Storage failure
must fail closed; no successful claim may be reported before it is persisted.
