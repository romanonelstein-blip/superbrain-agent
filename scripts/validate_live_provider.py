#!/usr/bin/env python3
"""Validate smoke output, not provider credentials or fixture-based evidence.

The caller must also require a zero exit status from the real smoke process.
A saved JSON report alone is not proof of its provenance or a full Nexus E2E.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def validate(report: object) -> bool:
    if not isinstance(report, dict) or report.get("liveSmoke") != "completed":
        return False
    results = report.get("results")
    if not isinstance(results, list) or not results:
        return False
    for result in results:
        if not isinstance(result, dict):
            return False
        if result.get("provider") not in ("openai", "anthropic", "gemini"):
            return False
        model = result.get("model")
        if not isinstance(model, str) or not model.strip():
            return False
        if result.get("attempted") is not True or result.get("success") is not True:
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Require a completed, successful live provider smoke report")
    parser.add_argument("report", type=Path)
    args = parser.parse_args(argv)
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("FAIL: live provider report is missing or invalid; contents withheld")
        return 1
    if not validate(report):
        print("FAIL: live provider report lacks successful, attempted external-provider results")
        return 1
    print("PASS: live provider smoke report validated (not full Nexus E2E proof)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
