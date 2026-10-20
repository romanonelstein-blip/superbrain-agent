# Skill intake safety baseline

## Required evidence before human approval
| Dimension | Minimum |
| --- | --- |
| Authenticity | Exact source URL, publisher identity, immutable revision |
| Integrity | Independently calculated SHA-256 of every reviewed executable and SKILL.md |
| License | Explicit compatibility review for copied code and bundled assets |
| Permission | Explicit access scope and data classifications |
| Execution | No scripts in discovery mode; isolated tests only after a separate execution permission |
| Assessment | Unit and adversarial fixtures; errors and uncertain claims visible |
| Ownership | Human reviewer with identity, timestamp, decision and content digest |
| Lifecycle | Expiration, version change review, rollback procedure, audit history |

## Workflow hard stops
- Reject malformed metadata, missing immutable provenance or digest mismatch.
- Quarantine requested write, shell execution, paid API or secret access for separate review.
- Quarantine suspicious instruction content, including hidden higher-priority instruction claims.
- Fail closed on unreadable archive, symlink traversal, unreviewed dependencies or unexpected network behavior.
- Reject any operation that lacks an explicit user/organization permission even if a skill claims it is safe.
- Run the first test on synthetic data with network egress off and no credentials.
- Record source digest and behavior test results. Never infer security from popularity or installation counts.

This baseline implements original project-specific review rules inspired by the Agent Skills open standard and emerging agent-skill security research. It is **not** a certification of third-party safety.

Sources: https://agentskills.io/specification ; https://arxiv.org/abs/2602.20156 ; https://github.com/OWASP/www-project-agentic-skills-top-10
