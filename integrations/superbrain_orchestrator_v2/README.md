# Superbrain Orchestrator v2 — Multi-model providers

This release turns the v1 provider placeholder into a real multi-model integration layer.

## What is included

- OpenAI adapter using the Responses API
- Anthropic adapter using the Messages API
- Gemini adapter using the stable Interactions API
- one provider contract for every Superbrain agent
- agent-to-provider routing policy
- automatic provider failover
- per-call timeout
- request/model/provider/latency metadata on each agent result
- API-key redaction in aggregated failover errors
- environment-based secrets and model overrides
- parser + failover + orchestration tests
- live smoke example

## Default models

The defaults match the vendor documentation checked on 2026-09-20 and can be overridden without code changes:

- OpenAI: `gpt-6-astra`
- Anthropic: `claude-sonnet-5`
- Gemini: `gemini-3.8-flash`

Set `OPENAI_MODEL`, `ANTHROPIC_MODEL`, or `GEMINI_MODEL` to pin another available model.

## Configure

Copy `.env.example` to `.env` in your runtime or configure environment variables in your deployment platform.

At least one provider key is required. With two or three keys, the ProviderRouter can fail over if a preferred provider fails.

Never put real API keys in source control.

## Run

```bash
npm install
npm test
npm run typecheck

# load environment variables using your runtime/platform,
# then execute:
npm run smoke
```

## Canonical Nexus bridge

This package is a provider/model-routing boundary. The Python `NexusOrchestrator`
is the canonical intelligence and decision runtime. To send one mission through
the provider layer, write a JSON request to stdin and run:

```bash
npm run nexus-bridge --silent
```

The command returns structured evidence with provider, model, agent, and request
provenance. Every item is `verified: false`; only the Python Evidence Graph/NEIS,
dissent, verifier, and final judge may approve a final result. Provider failures
exit non-zero and are never converted into a synthetic success.

The Python bridge also ignores any provider-supplied verification value. Promotion
to verified evidence requires `SourceEvidenceEnricher`: independently retrieved
source content, a matching quoted passage, and a separate stance-aware support
check. This keeps model generation and evidence verification on distinct trust
boundaries.

Execution provenance also includes provider attempts and latency. The deterministic
SB-016 integration fixture uses the real `ProviderRouter` and can be run without
secrets using `npm run nexus-bridge:fixture --silent`. It is test evidence, not a
production provider fallback.

## Routing defaults

- research -> Gemini -> OpenAI -> Anthropic
- strategy -> OpenAI -> Anthropic -> Gemini
- builder -> Anthropic -> OpenAI -> Gemini
- business -> OpenAI -> Anthropic -> Gemini
- finance -> OpenAI -> Anthropic -> Gemini
- critic -> Anthropic -> OpenAI -> Gemini
- verifier -> OpenAI -> Anthropic -> Gemini

Only configured providers are considered. The router automatically skips missing providers.

## Legacy compatibility limitation

The old `SuperbrainOrchestrator` name remains as a legacy internal wrapper. It delegates
directly to `runNexusProviderMission`, is not exported from the package public API, and
has no separate critic/verifier/synthesizer flow. Only Python Nexus may produce a
canonical final decision.

## Security choices

- no secrets are stored in the bundle
- API keys come only from environment variables or explicit constructor options
- provider errors are truncated and common key patterns are redacted
- network calls have explicit timeouts
- provider-specific code is isolated from orchestration logic
