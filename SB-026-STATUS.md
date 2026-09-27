# SB-026.2 — OSINT + Privacy Research Layer hardening

## Goal

SB-026.2 hardens live connectivity and Tor validation so provider tests no longer depend on the application already being configured in Tor mode.
Expand the existing research pipeline with GitHub intelligence, DuckDuckGo privacy search, configurable application-level egress routing, and controlled Tor/onion retrieval without creating a second decision engine.

## Canonical chain

`Mission → Research adapters → guarded source retrieval → Evidence → NexusOrchestrator → Verifier/Final Judge → persistence`

NexusOrchestrator remains the only final-decision engine.

## Research sources

- GitHub REST API repository search.
- Optional authenticated GitHub API via `GITHUB_TOKEN`; the token is never included in audit output.
- DuckDuckGo HTML search.
- Existing Tavily/Brave providers remain supported.
- Composite search deduplicates result URLs while preserving provider provenance.

GitHub public REST access can work without authentication; authentication can increase access/rate limits and unlock additional resources. See the official GitHub REST API documentation.

## Privacy / egress

Supported application-level modes:

- `direct`
- `http_proxy`
- `socks5`
- `tor`
- `auto` (opt-in local Tor/proxy detection)

Tor/SOCKS routing sends destination hostnames to the proxy rather than resolving them locally. `.onion` targets require both Tor mode and an explicit `SUPERBRAIN_ONION_ALLOWLIST` entry.

The system does **not** claim to make a user or application untraceable. A VPN/Tor can improve network privacy, but it does not remove endpoint, browser, provider, or operational risks.

## Onion / dark-web boundary

SB-026 does not implement an open-ended dark-web crawler or marketplace/index crawler. An onion URL must be explicitly supplied in the mission and its hostname must be on the configured allowlist. Retrieval is limited to the existing evidence pipeline and content-size/time guards.

This keeps the capability suitable for controlled OSINT/research rather than uncontrolled discovery or interaction with illicit services.

## Local stealth boundary

When `SUPERBRAIN_STEALTH_MODE=1`:

- Mission Control is loopback-only.
- Non-loopback binding is refused.
- A fresh API bearer token is generated when one is not configured.
- The token is passed to the locally opened browser through a URL fragment and stored in local browser storage.
- API routes require the token.
- No mDNS/UPnP/network discovery is implemented.
- HTTP access logging is suppressed.
- No telemetry feature is added.

This is a local privacy/isolation mode, not a guarantee of invisibility or anonymity.

## SB-026.2 live-test hardening

- Live smoke test now auto-detects local Tor SOCKS on ports 9150 and 9050.
- Windows launcher can auto-start an installed Tor Browser and wait for the SOCKS endpoint.
- A safe DuckDuckGo onion endpoint is used only as a temporary smoke-test target; production onion allowlisting remains explicit.
- `auto` egress mode can prefer a local Tor proxy without changing explicit direct/Tor/proxy modes.
- Explicit `direct` mode no longer inherits ambient HTTP(S) proxy variables for GitHub/DDG research; it uses public DNS resolution plus IP-pinned TLS.

## Verification

- Python suite: **231/231 passed**.
- SB-026 targeted tests: **11/11 passed**.
- Python compile gate: passed.
- Mission Control stealth smoke test: unauthenticated API `401`; token-authenticated API `200`.
- JavaScript syntax check: passed.
- Live GitHub/DuckDuckGo network calls were **not claimed as validated** in the build environment because outbound application networking was unavailable there.
- No provider credentials were added.

## Known limitation

The TypeScript provider workspace was not modified in SB-026. Its full `npm` verification could not be rerun in the current build environment because the Node development dependencies are not installed there. Existing generated bridge output was not rewritten.
