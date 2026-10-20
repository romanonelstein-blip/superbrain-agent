---
name: agent-evaluation-lab
description: Design and run reproducible AI agent workflow evaluations that measure tool behavior, evidence quality, safety, consistency, latency, and costs rather than answer quality alone. Use when creating or verifying SuperBrain agents or cross-project integrations.
---
# Agent Evaluation Lab

## Goal
Measure agent behavior across a complete trajectory, not merely whether the final text sounds plausible.

## Setup
1. Define task contract and success criteria from actual project requirements.
2. Capture a small set of deterministic positive examples, ambiguous cases, permission-denied cases, injected instructions, timeouts and malformed provider responses.
3. Run evaluations with fictional records; do not use real customer data or paid endpoints by default.
4. Record tool selection, argument validity, attempted privilege escalation, external effects, evidence provenance, latency, failures and token or credit usage.
5. Have a separate reviewer or reproducible invariant judge compliance. Never assume an LLM judge is ground truth.
6. Execute negative tests first: unauthorized writes, tenant boundary crossing, leaked secrets, ignored opt-outs, duplicate bills, and false NEXUS approval.
7. Report results per exact version: passed/total, coverage gaps, median and tail latency if measured, costs if observed, and repeatability.
8. Allow promotion only when release-specific safety and correctness gates pass. If a required fixture is missing, status is PARTIAL, not PASS.

## Evaluation record
Use [agent evaluation contract](../references/agent-evaluation-contract.md).

## Project application
SuperBrain: multi-agent decisions and NEXUS gates. NovaProspects: provider signal accuracy, action policy and isolated tenants. Fondio: user journeys, fraud-review tooling and checkout simulations.
