from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from nexus1000.network import (
    EgressConfig,
    NetworkPolicyError,
    detect_local_tor_proxy,
    is_tcp_port_open,
    validate_public_or_onion_target,
)
from nexus1000.research import (
    DuckDuckGoSearchClient,
    GitHubSearchClient,
    ResearchUnavailableError,
    SafeResearchSourceFetcher,
    SearchHit,
    Stance,
    _read_https_bytes,
)

# Safe, public onion smoke target: DuckDuckGo's onion service, documented by the
# Tor Project. This is used only by this test and is NOT added to production config.
SAFE_ONION_URL = "https://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/"
SAFE_ONION_HOST = urlsplit(SAFE_ONION_URL).hostname or ""


def line(label: str, status: str, detail: str = "") -> None:
    print(f"[{status}] {label}" + (f" — {detail}" if detail else ""))


def check_provider(label: str, fn) -> bool:
    started = time.perf_counter()
    try:
        value = fn()
        ms = (time.perf_counter() - started) * 1000
        line(label, "PASS", f"{value} ({ms:.0f} ms)")
        return True
    except Exception as exc:
        ms = (time.perf_counter() - started) * 1000
        line(label, "FAIL", f"{type(exc).__name__}: {exc} ({ms:.0f} ms)")
        return False


def _tor_browser_candidates() -> tuple[Path, ...]:
    home = Path.home()
    appdata = Path(os.getenv("APPDATA", "")) if os.getenv("APPDATA") else None
    localappdata = Path(os.getenv("LOCALAPPDATA", "")) if os.getenv("LOCALAPPDATA") else None
    candidates: list[Path] = []
    explicit = os.getenv("TOR_BROWSER_PATH", "").strip()
    if explicit:
        candidates.append(Path(explicit))
    if appdata:
        candidates.extend([
            appdata / "Tor Browser" / "Start Tor Browser.lnk",
            appdata / "Tor Browser" / "Browser" / "firefox.exe",
            appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Tor Browser" / "Tor Browser.lnk",
        ])
    if localappdata:
        candidates.extend([
            localappdata / "Tor Browser" / "Start Tor Browser.lnk",
            localappdata / "Tor Browser" / "Browser" / "firefox.exe",
        ])
    candidates.extend([
        home / "Desktop" / "Tor Browser.lnk",
        home / "Desktop" / "Tor Browser" / "Start Tor Browser.lnk",
        home / "Downloads" / "tor-browser" / "Start Tor Browser.exe",
        Path("C:/Program Files/Tor Browser/Start Tor Browser.lnk"),
        Path("C:/Program Files/Tor Browser/Browser/firefox.exe"),
        Path("C:/Program Files (x86)/Tor Browser/Start Tor Browser.lnk"),
        Path("C:/Program Files (x86)/Tor Browser/Browser/firefox.exe"),
    ])
    return tuple(dict.fromkeys(path for path in candidates if path.exists()))


def _start_tor_browser_if_available() -> bool:
    if os.name != "nt" or os.getenv("SUPERBRAIN_AUTO_START_TOR", "0").strip() != "1":
        return False
    candidates = _tor_browser_candidates()
    if not candidates:
        line("Tor Browser auto-start", "INFO", "Tor Browser was not found in common Windows locations")
        return False
    target = candidates[0]
    try:
        if target.suffix.casefold() == ".lnk":
            os.startfile(str(target))  # type: ignore[attr-defined]
        else:
            subprocess.Popen([str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        line("Tor Browser auto-start", "PASS", f"started {target.name}; waiting for local SOCKS port")
        return True
    except OSError as exc:
        line("Tor Browser auto-start", "FAIL", f"could not start {target.name}: {exc}")
        return False


def _wait_for_tor_proxy(seconds: float | None = None) -> tuple[str, int] | None:
    if seconds is None:
        seconds = float(os.getenv("SUPERBRAIN_TOR_STARTUP_WAIT_SECONDS", "45"))
    deadline = time.monotonic() + max(0.0, seconds)
    while time.monotonic() < deadline:
        detected = detect_local_tor_proxy()
        if detected is not None:
            return detected
        time.sleep(0.5)
    return None


def _run_provider_suite(label_prefix: str, egress: EgressConfig, *, test_onion: bool = False) -> tuple[bool, list[SearchHit], list[SearchHit]]:
    github = GitHubSearchClient(token=os.getenv("GITHUB_TOKEN", ""), egress=egress)
    ddg = DuckDuckGoSearchClient(egress=egress)
    fetcher = SafeResearchSourceFetcher(egress=egress)
    github_hits: list[SearchHit] = []
    ddg_hits: list[SearchHit] = []
    ok = True

    def github_check():
        github_hits.extend(github.search("openai python", 2))
        if not github_hits:
            raise RuntimeError("GitHub returned no repositories")
        return f"{len(github_hits)} result(s); first={github_hits[0].url}"

    def ddg_check():
        ddg_hits.extend(ddg.search("SuperBrain AI", 2))
        if not ddg_hits:
            raise RuntimeError("DuckDuckGo returned no results")
        return f"{len(ddg_hits)} result(s); first={ddg_hits[0].url}"

    ok &= check_provider(f"{label_prefix} GitHub live search", github_check)
    ok &= check_provider(f"{label_prefix} DuckDuckGo live search", ddg_check)

    if github_hits:
        ok &= check_provider(
            f"{label_prefix} GitHub source retrieval",
            lambda: fetcher.fetch(github_hits[0]).content_hash[:16],
        )
    if ddg_hits:
        ok &= check_provider(
            f"{label_prefix} DuckDuckGo source retrieval",
            lambda: fetcher.fetch(ddg_hits[0]).content_hash[:16],
        )

    if egress.tor_enabled:
        def tor_check():
            status, _headers, raw = _read_https_bytes(
                "https://check.torproject.org/api/ip",
                timeout=egress.timeout_seconds,
                max_bytes=32_000,
                egress=egress,
                headers={"Accept": "application/json", "User-Agent": "SuperBrain-SB026-SmokeTest/1"},
            )
            if status != 200:
                raise RuntimeError(f"Tor check returned HTTP {status}")
            payload = json.loads(raw.decode("utf-8"))
            if payload.get("IsTor") is not True:
                raise RuntimeError(f"Tor endpoint did not confirm IsTor=true: {payload}")
            return "IsTor=true; exit_ip=hidden"

        ok &= check_provider(f"{label_prefix} Tor egress", tor_check)

        if test_onion:
            try:
                validate_public_or_onion_target(SAFE_ONION_HOST, egress)
                onion_hit = SearchHit(
                    "DuckDuckGo official onion smoke test",
                    SAFE_ONION_URL,
                    "Controlled public onion connectivity test",
                    "tor-direct",
                    1,
                    "explicit safe onion smoke test",
                    Stance.NEUTRAL,
                )
                ok &= check_provider(
                    f"{label_prefix} Safe onion retrieval",
                    lambda: fetcher.fetch(onion_hit).content_hash[:16],
                )
            except Exception as exc:
                line(f"{label_prefix} Safe onion retrieval", "FAIL", f"{type(exc).__name__}: {exc}")
                ok = False

    return ok, github_hits, ddg_hits


def main() -> int:
    print("SuperBrain SB-026.1 — LIVE OSINT / EGRESS SMOKE TEST")
    print("No credential values are printed or logged.")
    print("The test uses the same GitHub/DDG/evidence adapters as SuperBrain.")
    print()

    try:
        configured = EgressConfig.from_env()
    except Exception as exc:
        line("Configured egress", "FAIL", f"{type(exc).__name__}: {exc}")
        return 2

    token_present = bool(os.getenv("GITHUB_TOKEN", "").strip())
    line(
        "Configured egress",
        "PASS",
        f"mode={configured.mode}, proxy={configured.proxy_host}:{configured.proxy_port}, onion_allowlist={len(configured.onion_allowlist)}",
    )
    line(
        "GitHub token",
        "READY" if token_present else "INFO",
        "configured (value hidden)" if token_present else "not configured; public GitHub API will be tested",
    )

    overall_ok, _github_hits, _ddg_hits = _run_provider_suite("Configured", configured, test_onion=False)

    # Always probe Tor separately. This fixes the previous behavior where Tor was
    # skipped merely because SUPERBRAIN_EGRESS_MODE was not set to 'tor'.
    detected_tor = detect_local_tor_proxy()
    if detected_tor is None:
        _start_tor_browser_if_available()
        detected_tor = _wait_for_tor_proxy(45.0)

    if detected_tor is None:
        line("Tor egress", "ACTION", "no local Tor SOCKS proxy detected on 127.0.0.1:9150 or :9050")
        line("Safe onion retrieval", "ACTION", "will run automatically when Tor is available; target is the official DuckDuckGo onion service")
        # Do not turn a missing optional Tor installation into a false provider failure.
        # The configured GitHub/DDG result still determines the exit code.
    else:
        tor_host, tor_port = detected_tor
        tor_allowlist = tuple(dict.fromkeys(configured.onion_allowlist + (SAFE_ONION_HOST,)))
        tor_config = EgressConfig(
            mode="tor",
            proxy_host=tor_host,
            proxy_port=tor_port,
            onion_allowlist=tor_allowlist,
            timeout_seconds=configured.timeout_seconds,
        )
        line("Tor proxy discovery", "PASS", f"127.0.0.1:{tor_port}")
        tor_ok, _tor_github, _tor_ddg = _run_provider_suite("Tor", tor_config, test_onion=True)
        overall_ok &= tor_ok

    print()
    if overall_ok:
        print("LIVE_SMOKE_TEST=PASS")
        return 0
    print("LIVE_SMOKE_TEST=FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
