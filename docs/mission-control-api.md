# Mission Control API

Mission Control is the HTTP boundary used by the SuperBrain iOS app.

## Security model

- bearer token authentication is mandatory;
- tokens shorter than 20 characters are rejected;
- responses use no-store and restrictive security headers;
- the standalone server binds to loopback by default;
- a non-loopback HTTP bind is refused unless explicitly overridden;
- remote iPhone access should terminate TLS in front of Mission Control;
- mission execution is fail-closed when no real `MissionExecutor` is attached.

The standalone command never invents NEXUS evidence or results. It now
uses `NexusMissionExecutor` to connect Mission Control to the canonical
NEXUS bridge, but still reports interactive and research missions
unavailable until a real evidence provider is integrated.

`NexusMissionExecutor` only exposes mobile `YES` when the NEXUS decision
is actually approved after all canonical gates. A raw `YES` with a failed
gate becomes mobile `NO`. Gate outcomes are written into the mission
audit trail.

## Start

Build first:

```bash
npm run build
```

Set a secret locally (never commit it):

```bash
SUPERBRAIN_MISSION_CONTROL_TOKEN='replace-with-a-long-random-secret' npm run start:mobile-api
```

Defaults:

- host: `127.0.0.1`
- port: `8787`
- data: `.superbrain/mission-control/missions.json`

For an iPhone on another device/network, put this HTTP service behind a
trusted HTTPS endpoint. The iOS client intentionally rejects ordinary
remote HTTP.

## Routes

- `GET /api/system/status`
- `GET /api/missions`
- `GET /api/missions/{runId}`
- `POST /api/missions/ask`
- `POST /api/missions/research`
- `POST /api/missions/{runId}/master-decision`

The server also advertises the SuperBrain version, mobile API version and
capability IDs so the iOS app can detect compatibility drift.

## Evidence provider

To make interactive/research missions available, configure a protocol-v1
evidence provider with `SUPERBRAIN_EVIDENCE_PROVIDER_COMMAND`. See
`docs/evidence-provider-protocol.md`.

Mission Control calls the provider without a shell, validates all returned
provenance, then sends the evidence to NEXUS. Provider output alone can
never grant approval.

## Built-in HTTP research mode

Mission Control can use the built-in HTTP research provider instead of a
command evidence provider. Configure both
`SUPERBRAIN_RESEARCH_PRIMARY_ENDPOINT` and
`SUPERBRAIN_RESEARCH_DISSENT_ENDPOINT`.

SuperBrain performs the actual source fetches and hashes the retrieved
bytes before sending evidence to NEXUS. See
`docs/http-research-provider.md`.
