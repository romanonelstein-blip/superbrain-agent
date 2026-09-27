# Built-in HTTP Research Provider

The built-in research provider turns discovery results into evidence that
SuperBrain verifies itself before NEXUS sees it.

It uses two independently identified discovery providers:

1. primary discovery;
2. dissent discovery.

Both discovery endpoints receive the same mission question, but dissent is
requested with stance `challenge`. SuperBrain then fetches every returned
source URL itself, applies network safety checks, limits response sizes,
extracts usable text, computes a SHA-256 hash over the retrieved bytes and
creates the NEXUS provenance fields.

## Configure

Required:

- `SUPERBRAIN_RESEARCH_PRIMARY_ENDPOINT`
- `SUPERBRAIN_RESEARCH_DISSENT_ENDPOINT`

Optional:

- `SUPERBRAIN_RESEARCH_PRIMARY_NAME`
- `SUPERBRAIN_RESEARCH_DISSENT_NAME`
- `SUPERBRAIN_RESEARCH_PRIMARY_TOKEN`
- `SUPERBRAIN_RESEARCH_DISSENT_TOKEN`
- `SUPERBRAIN_RESEARCH_ALLOWED_HOSTS` as a comma-separated source-host allowlist

Do not configure the command evidence provider at the same time. Mission
Control refuses ambiguous dual configuration.

## Discovery protocol

Status request:

```json
{"protocolVersion":1,"type":"status"}
```

Status response:

```json
{"protocolVersion":1,"ready":true}
```

Search request:

```json
{
  "protocolVersion": 1,
  "type": "search",
  "query": "mission question",
  "mode": "research",
  "limit": 6,
  "requestedStance": "neutral"
}
```

Dissent uses `requestedStance: "challenge"`.

Search response:

```json
{
  "protocolVersion": 1,
  "results": [
    {
      "url": "https://example.org/source",
      "title": "Optional title",
      "snippet": "Optional discovery snippet",
      "stance": "neutral"
    }
  ]
}
```

## Network safety

Production behavior is fail-closed:

- discovery and source URLs require HTTPS;
- embedded URL credentials are rejected;
- localhost, private, link-local, multicast and common reserved IP ranges are rejected;
- DNS results resolving to private/reserved IPs are rejected;
- redirects are manually followed and revalidated at every hop;
- source and discovery response sizes are capped;
- only textual HTML/plain/JSON/XML source types are accepted;
- source fetches never receive discovery bearer tokens;
- an optional source-host allowlist can further restrict retrieval.

Private HTTP networking exists only behind explicit constructor flags used
by deterministic tests and is not enabled by the Mission Control launcher.

## Evidence semantics

A successfully retrieved source becomes verified evidence with:

- stable ID derived from the canonical URL;
- citation equal to the final fetched URL;
- source family equal to the hostname;
- SHA-256 content hash over the actual response bytes;
- retrieval timestamp and content type;
- provider identity;
- extracted source text included in the claim.

Primary evidence defaults to neutral stance. Dissent evidence defaults to
challenge stance. Discovery endpoints can provide a valid explicit stance.

The provider does not make the final decision. NEXUS remains the only
decision boundary.
