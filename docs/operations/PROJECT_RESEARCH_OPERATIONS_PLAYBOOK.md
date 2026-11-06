# Project Research & Operations Playbook

## Purpose
Reusable, evidence-first workflows for this repository. Write in clear Dutch at B1 level unless the task requests another language. Never invent facts, metrics, sources, quotations, test results, or implementation status.

## Scope and safety
- This file is guidance, not proof that any workflow or control is implemented.
- Keep this repository's secrets, data, analytics, environments, and brand separate from SuperBrain, NovaProspects, and Fondio.
- Inspect current repository evidence before acting. Label verified facts, assumptions, unknowns, and recommendations separately.
- Read-only checks may run directly. Do not change production, databases, credentials, billing, send external messages, publish, or merge without appropriate approval.
- For code changes, use a branch and pull request, test the exact commit, document evidence, and retain human release approval.
- Never run unknown scripts/skills or send confidential data to third-party services.

## Workflow 1: Market research
Research company activity, products, audience, market size/growth, competitors and prices, two-year trends, and entry barriers. Cite each material claim with a source link and date when available. If a figure cannot be found reliably, say so. End with three evidence-backed opportunities for a small business. Do not invent TAM/SAM/SOM inputs.

## Workflow 2: Laws, regulation, and subsidies
Use primary official sources first (laws, government, regulators, EU institutions). Create a table with rule, required action, effective date/transition, official source, status, and uncertainty. Distinguish current law, adopted future rules, proposals, and guidance. Flag conflicts and recommend legal/accounting review where material. Do not present this as legal advice.

## Workflow 3: Customer voice
Search relevant, accessible reviews, forums, social media, and trade publications. Summarize up to five recurring frustrations and five wishes. Only claim frequency when the sample supports it. Use short, verifiable quotations with direct links; never fabricate quotes or imply a small sample represents everyone. Separate observations from hypotheses.

## Workflow 4: Spreadsheet and dashboard
Check data types, missing values, duplicates, inconsistent labels, date ranges, currencies, units, and outliers before analysis. Produce requested charts only when the necessary columns exist. Show formulas, definitions, limitations, and plain-language takeaways. Preserve the original data; document edits and flag ambiguous duplicates rather than merging by guesswork.

## Workflow 5: Scenario analysis
Record the decision, inputs, period, and formulas. Calculate scenarios transparently and compare them in a table. Identify sensitive assumptions when the data permits. Ask for missing critical inputs or show an explicit blank input template; do not invent values.

## Workflow 6: Prompt design
Clarify goal, audience, context, desired output, and success criteria. Select a suitable framework as a flexible aid, not a rigid template. Draft a reusable Markdown prompt with role, task, context, steps, output, and stop condition. Check source quality, privacy, uncertainty, assumptions, and feasibility.

## Workflow 7: Reusable skills
Specify trigger, inputs, constraints, steps, output, failure handling, acceptance criteria, and edge cases. Test at least one normal case and one missing/ambiguous-input case. Report exactly what was tested. Seek confirmation before external publication or risky activation.

## Workflow 8: Practice conversations
Clarify role, offer, price, context, and challenge. Keep roleplay clearly simulated. Stop when asked and give three concrete, respectful improvement points.

## Standard evidence and reporting
- Put source links next to claims.
- For laws, prefer official sources. For customer research, cite original sources and keep quotations short.
- For calculations, show formulas and input provenance.
- End each work item with: (1) work performed, (2) evidence links, (3) uncertainties/blockers, (4) next priority.
- Explicitly say "not found", "not checked", or "not run" when applicable.
- A green CI run applies only to its exact commit/workflow; do not generalize it to another branch or release.
