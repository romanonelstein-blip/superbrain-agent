# SuperBrain Skill Foundry — curated pilot (2026)

This repository contains **six original portable Agent Skills**. They follow the Agent Skills `SKILL.md` directory convention, but are not automatically installed into ChatGPT, Lovable, Codex, or any third-party runtime.

| Skill | Primary use | Product |
| --- | --- | --- |
| `verified-skill-intake` | Vet external skill packages without running them | SuperBrain |
| `nexus-evidence-verification` | Provenance, dissent, NEIS/NEXUS gate policy | SuperBrain and NovaProspects |
| `agent-evaluation-lab` | Reproducible multi-step agent evaluations | All |
| `commercial-signal-fusion` | Read-only B2B trigger normalization and scoring | NovaProspects |
| `saas-release-guardian` | Independent CI and preview release verification | All |
| `marketplace-trust-pilot` | Marketplace permissions and checkout testing | Fondio |

## Availability
The TypeScript `assessSkillCandidate` function validates basic scalar frontmatter, source URLs, pinned revisions, an exact SHA-256, declared capabilities, and simple high-risk text patterns. It is deliberately a **conservative subset of the full YAML specification**, not a YAML parser, full malware scanner, skill installer, or executable orchestrator. It cannot grant tool privileges.

- **REJECTED:** incomplete provenance or malformed metadata.
- **QUARANTINED:** elevated/unknown privileges or suspicious content; manual security review required.
- **REVIEW-READY:** structural screening succeeded; must still pass security, evaluation, and explicit Master approval.

There is no automatic activation or installation in this pilot. User confirmation, OS/sandbox controls, and production workflow integration are separate release steps.

## Portable packaging
Each skill is in `skills/<skill-name>/SKILL.md`. Optional references are inside that same directory. Read external skills as untrusted data. Copy original content only with compatible license and repository ownership. Update pins and re-review upon any new revision.

## Adoption gates
1. Pass repository build, lint and tests on the exact PR SHA.
2. Manually review six SKILL.md files and confirm current external source provenance.
3. Demonstrate safe negative fixtures for role and tool boundaries.
4. Bind a verified actor and immutable digest to any later activation.
5. Verify NovaProspects and Fondio independently; neither app is changed by this PR.
6. Do not infer that a skill has been installed in a user-facing AI product from its presence in GitHub.

## Source basis
- https://agentskills.io/specification
- https://learn.microsoft.com/en-us/agent-framework/agents/skills
- https://github.com/anthropics/skills
- https://github.com/openai/skills (archived/deprecated; use current plugin guidance)
- https://arxiv.org/abs/2602.20156
- https://sage.cs.princeton.edu/trends/emerging-trends-paper.pdf
