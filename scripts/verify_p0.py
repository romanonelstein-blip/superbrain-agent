#!/usr/bin/env python3
from __future__ import annotations
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TS_DIR = ROOT / "integrations" / "superbrain_orchestrator_v2"

def run_live_model() -> bool:
    """Only the real bounded smoke process plus its validated report can pass."""
    env = os.environ.copy()
    env["SUPERBRAIN_LIVE_PROVIDER_SMOKE"] = "1"
    with tempfile.TemporaryDirectory(prefix="superbrain-live-") as directory:
        report = Path(directory) / "live-provider-result.json"
        try:
            with report.open("w", encoding="utf-8") as output:
                process = subprocess.run(
                    ["node", "dist/src/sb021-live-smoke.js"], cwd=str(TS_DIR),
                    env=env, stdout=output, stderr=subprocess.DEVNULL,
                    timeout=90, check=False,
                )
        except (OSError, subprocess.TimeoutExpired):
            print("FAIL: live provider process could not complete; raw output withheld")
            return False
        if process.returncode != 0:
            print("FAIL: live provider process failed; raw output withheld")
            return False
        return run("Live provider report validation", [
            sys.executable, str(ROOT / "scripts" / "validate_live_provider.py"), str(report)
        ])

def run(label: str, cmd: list[str], cwd: Path = ROOT) -> bool:
    print(f"\n=== {label} ===")
    print(">", " ".join(cmd))
    try:
        result = subprocess.run(cmd, cwd=str(cwd), check=False)
    except FileNotFoundError:
        print(f"FAIL: executable not found: {cmd[0]}")
        return False
    ok = result.returncode == 0
    print("PASS" if ok else f"FAIL (exit {result.returncode})")
    return ok

def main() -> int:
    ap = argparse.ArgumentParser(description="SuperBrain SB-034 P0 technical and live-smoke verifier")
    ap.add_argument("--live", action="store_true",
                    help="Run live provider smoke tests when matching credentials are present.")
    ap.add_argument("--skip-install", action="store_true",
                    help="Do not run npm ci when node_modules is missing.")
    args = ap.parse_args()

    results: list[tuple[str, bool]] = []

    results.append(("Python regression",
                    run("Python regression", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test*.py"])))
    results.append(("Python compile",
                    run("Python compile", [sys.executable, "-m", "compileall", "-q", "nexus1000", "tests"])))

    node_ok = shutil.which("node") is not None and shutil.which("npm") is not None
    print("\n=== Node/npm preflight ===")
    print("PASS" if node_ok else "FAIL: node/npm not found")
    results.append(("Node/npm available", node_ok))

    deps_ok = False
    if node_ok and TS_DIR.exists():
        package_lock = TS_DIR / "package-lock.json"
        print(f"package-lock.json: {'present' if package_lock.exists() else 'missing'}")
        node_modules = TS_DIR / "node_modules"
        if not node_modules.exists() and not args.skip_install:
            deps_ok = run("npm clean install",
                          ["npm", "ci", "--no-audit", "--no-fund"], TS_DIR)
        else:
            deps_ok = node_modules.exists()
            print(f"node_modules: {'present' if deps_ok else 'missing (install skipped)'}")
        results.append(("npm dependencies", deps_ok))

        if deps_ok:
            results.append(("TypeScript tests", run("TypeScript tests", ["npm", "test"], TS_DIR)))
            results.append(("TypeScript typecheck", run("TypeScript typecheck", ["npm", "run", "typecheck"], TS_DIR)))
            results.append(("TypeScript bridge build", run("TypeScript bridge build", ["npm", "run", "build:bridge"], TS_DIR)))
        else:
            results.extend([
                ("TypeScript tests", False),
                ("TypeScript typecheck", False),
                ("TypeScript bridge build", False),
            ])

    model_keys = {
        "OPENAI_API_KEY": bool(os.getenv("OPENAI_API_KEY")),
        "ANTHROPIC_API_KEY": bool(os.getenv("ANTHROPIC_API_KEY")),
        "GEMINI_API_KEY": bool(os.getenv("GEMINI_API_KEY")),
    }
    research_keys = {
        "TAVILY_API_KEY": bool(os.getenv("TAVILY_API_KEY")),
        "BRAVE_SEARCH_API_KEY": bool(os.getenv("BRAVE_SEARCH_API_KEY")),
    }

    print("\n=== Live-provider readiness ===")
    for key, present in {**model_keys, **research_keys}.items():
        print(f"{key}: {'configured' if present else 'missing'}")

    model_ready = any(model_keys.values())
    research_ready = any(research_keys.values())
    results.append(("Model-provider credentials", model_ready))
    results.append(("Research-provider credentials", research_ready))

    if args.live:
        if deps_ok and model_ready:
            results.append(("Live model-provider smoke",
                            run_live_model()))
        else:
            print("\nLive model-provider smoke: SKIPPED (dependencies or credentials missing)")

        if research_ready:
            results.append(("Live OSINT connectivity smoke",
                            run("Live OSINT connectivity smoke", [sys.executable, "live_osint_smoke_test.py"], ROOT)))
        else:
            print("Live OSINT connectivity smoke: SKIPPED (research credentials missing)")

    print("\n=== P0 SUMMARY ===")
    for name, ok in results:
        print(f"{'PASS' if ok else 'OPEN'}  {name}")

    hard_gates = [
        name for name, ok in results
        if name in {
            "Python regression",
            "Python compile",
            "Node/npm available",
            "npm dependencies",
            "TypeScript tests",
            "TypeScript typecheck",
            "TypeScript bridge build",
        } and not ok
    ]
    if hard_gates:
        print("\nP0 RESULT: OPEN")
        print("Unclosed technical gates:", ", ".join(hard_gates))
        return 1

    if not (model_ready and research_ready):
        print("\nP0 RESULT: TECHNICAL GATES PASS, LIVE PROVIDER PROOF STILL OPEN")
        return 2

    if args.live:
        live_failures = [name for name, ok in results if name.startswith("Live ") and not ok]
        if live_failures:
            print("\nP0 RESULT: OPEN")
            return 3
        print("\nP0 RESULT: TECHNICAL AND CONNECTIVITY SMOKE GATES PASS")
        print("Full research-provider and canonical Nexus live E2E proof remain separate gates.")
        return 0

    print("\nP0 RESULT: TECHNICAL GATES PASS; rerun with --live for provider proof")
    return 2

if __name__ == "__main__":
    raise SystemExit(main())
