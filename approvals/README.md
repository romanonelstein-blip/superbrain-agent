# SB-020 approval and apply contract

SB-020 is a local, approval-gated transaction layer. It does not deploy.

## Authority

- The source experiment must be immutable, completed, and `ELIGIBLE_FOR_APPROVAL`.
- An approval is canonical JSON content-addressed with SHA-256 and authenticated with
  HMAC-SHA256 using a human-controlled secret of at least 32 bytes.
- The signed payload binds experiment ID, snapshot digest, candidate ID, Golden suite digest,
  approver identity, exact approval intent, nonce, timestamp, and signer kind `HUMAN`.
- The apply engine verifies but never creates approvals.
- AI, agent, service, and automated signer kinds are rejected.
- Each approval digest is usable once. A failed or rolled-back attempt still consumes it.

## Apply transaction

Only `sb020.apply.v1` JSON is accepted. It contains one to twenty `replace` operations. Every
operation names an existing regular non-symlink target inside the selected workspace, an
immutable candidate artifact, and the exact expected SHA-256 of the target. There is no shell,
Python, hook, delete, rename, network, package installation, Git, merge, or deployment action.

The engine verifies all preconditions, records a content-addressed pre-apply snapshot, consumes
the approval transactionally, uses atomic file replacement, runs the unchanged Golden suite,
and compares the realized behavior with the eligible experiment report. Any exception or
regression restores every target and verifies both restored hashes and Golden behavior.

## Audit data

SQLite stores immutable approval payloads/signatures, one-time consumption, transaction state,
pre-snapshot hashes, post-apply report, regressions, rollback verification, timestamps, errors,
and ordered events. Terminal records and events are immutable and records cannot be deleted.

## Scope boundary

This protects controlled local configuration/artifact replacement. It is not a deployment
system and is not an OS sandbox for hostile trusted-runtime code. Production approval keys
belong in a human-operated signing service or hardware-backed key boundary.
