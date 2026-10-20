---
name: nexus-evidence-verification
description: Verify structured facts, citations, uncertainties, dissent, freshness, and NEXUS-1000 NEIS gates before an AI recommendation is shown as authoritative. Use for SuperBrain agent outcomes, CRM signal briefs, research, and decision support.
---
# NEXUS Evidence Verification

## When activated
Apply to recommendations that combine external evidence, AI analysis, CRM data or consequential advice.

## Process
1. Identify the precise decision question, accountable workspace, sources, and evaluation timestamp.
2. Split observed facts from interpretations, predictions, assumptions, and unsupported statements.
3. Record for each material fact: stable evidence ID, source ID, source family, citation, retrieval time, optional event time, and content hash.
4. Verify claims using independent source families where possible, not two copies of one article.
5. Evaluate contradictory observations; record explicit challenge evidence and residual uncertainty.
6. Feed structured evidence into the existing canonical NEXUS bridge. Never fabricate a successful evaluation when the Python runtime is missing.
7. Require explicit true results for grand_council, neis, blinded_dissent, and verifier. Any missing, timeout, or failed gate means NO.
8. Keep an AI recommendation distinct from actual Master approval for action. Verified content alone never authorizes outreach, spending or writing.
9. Deliver conclusion, supporting evidence, objections, confidence limits, applicable policy and an auditable next step.

## Failure cases
Missing source? UNVERIFIED. Conflicting timestamps? NEEDS REVIEW. No canonical NEXUS runtime? BLOCKED. Human approval expired or action changed? DO NOT EXECUTE.

## Product use
SuperBrain runs evaluations; NovaProspects displays sources and review status; Fondio can use evidence checks for internal moderation recommendations without automatic account sanctions.
