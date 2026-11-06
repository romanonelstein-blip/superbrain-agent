#!/usr/bin/env python3
"""Fail-closed, dependency-free committed-secret check, including ZIP members.

Reports file location and signature type only; it never prints a candidate secret.
This complements, but does not replace, native GitHub secret scanning.
"""
from __future__ import annotations

import io
import pathlib
import re
import subprocess
import sys
import zipfile

MAX_FILE = 8 * 1024 * 1024
MAX_ARCHIVE_MEMBER = 4 * 1024 * 1024
MAX_ARCHIVE_TOTAL = 48 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 3000

SIGNATURES = (
    ("private key", re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("GitHub credential", re.compile(rb"\b(?:ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,})\b")),
    ("AWS access key", re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("OpenAI-style token", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("Slack bot/user token", re.compile(rb"\bxox[aboprs]-[A-Za-z0-9-]{20,}\b")),
)


def detect(content: bytes) -> list[str]:
    """Find credential-shaped patterns; never return or log their actual value."""
    return [label for label, pattern in SIGNATURES if pattern.search(content)]


def scan_archive(content: bytes, location: str) -> tuple[list[str], list[str]]:
    findings: list[str] = []
    errors: list[str] = []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                return [], [f"{location}: too many ZIP entries to verify"]
            total = 0
            for entry in infos:
                if entry.is_dir():
                    continue
                total += entry.file_size
                if entry.file_size > MAX_ARCHIVE_MEMBER or total > MAX_ARCHIVE_TOTAL:
                    errors.append(f"{location}: ZIP member exceeds safe scan size")
                    continue
                try:
                    data = archive.read(entry)
                except (OSError, RuntimeError, zipfile.BadZipFile, ValueError):
                    errors.append(f"{location}: unreadable ZIP member")
                    continue
                for label in detect(data):
                    findings.append(f"{location}: possible {label} in ZIP member")
    except (OSError, RuntimeError, zipfile.BadZipFile, ValueError):
        errors.append(f"{location}: unreadable ZIP archive")
    return findings, errors


def scan_repo(root: pathlib.Path) -> tuple[list[str], list[str]]:
    root = root.resolve()
    try:
        raw = subprocess.check_output(["git", "ls-files", "-z"], cwd=root, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return [], ["Cannot list tracked files; refusing to claim a completed scan"]
    findings: list[str] = []
    errors: list[str] = []
    for token in raw.split(b"\0"):
        if not token:
            continue
        relative = token.decode("utf-8", errors="replace")
        path = root / relative
        if path.is_symlink():
            errors.append(f"{relative}: symbolic link requires review")
            continue
        if not path.is_file():
            errors.append(f"{relative}: tracked file not readable")
            continue
        if path.stat().st_size > MAX_FILE:
            errors.append(f"{relative}: tracked file too large to verify")
            continue
        try:
            data = path.read_bytes()
        except OSError:
            errors.append(f"{relative}: tracked file not readable")
            continue
        for label in detect(data):
            findings.append(f"{relative}: possible {label}")
        if relative.lower().endswith(".zip"):
            matched, failed = scan_archive(data, relative)
            findings.extend(matched)
            errors.extend(failed)
    return findings, errors


def main() -> int:
    findings, errors = scan_repo(pathlib.Path("."))
    for notice in findings + errors:
        print("::error::" + notice.replace("\n", " "))
    if findings or errors:
        print(f"Secret audit blocked: {len(findings)} suspect signature(s), {len(errors)} unscanned item(s).")
        return 1
    print("Secret audit passed for tracked files and ZIP members (signature coverage is not exhaustive).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
