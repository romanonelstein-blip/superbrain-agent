# Superbrain skills

This directory contains first-party, reviewable skill instructions for Superbrain-compatible agents. Skills here are plain Markdown instructions; they do not bundle executable code, install dependencies, make network calls, or request credentials.

## Available skill

- [`superbrain-repo-audit`](./superbrain-repo-audit/SKILL.md) — read-only, evidence-based repository audit and prioritized engineering recommendations.

## Trust and review policy

- Treat skills from external repositories as untrusted until their complete contents, license, provenance, and behavior have been reviewed.
- Do not auto-download, auto-install, or execute third-party skills or scripts.
- Review changes to skills like application code. Keep requested permissions minimal and require human approval for writes, external calls, secret access, merges, and deployments.
- A skill's presence is not proof that its recommendations or any software it discusses are safe or tested.
- Validate claims against the exact repository revision and current CI results; never infer a pass from an old commit or badge alone.
