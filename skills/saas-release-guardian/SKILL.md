---
name: saas-release-guardian
description: Independently verify code, CI, deployment previews, database migrations, tenant safety, credentials and release readiness before promoting changes in NovaProspects, SuperBrain, or Fondio. Use for feature branches, pull requests, beta releases and incidents.
---
# SaaS Release Guardian

## Verification order
1. Identify the exact repository, branch, commit SHA, deployment project and requested environment.
2. Read build rules, tests, CI workflows, current PR diff and deployment configuration.
3. Independently check formatting, lint, types, unit tests, relevant integration tests, dependency security and build.
4. For multi-tenant apps verify negative authorization tests and migration rollback on an isolated database.
5. Check deployment status for the **same SHA**, not a previous successful commit or a different Vercel project.
6. Check that preview secrets belong to isolated preview resources. Never copy production database secrets into preview merely to get a green deployment.
7. Distinguish code CI success from runtime availability and end-to-end user flows.
8. Publish a release matrix: PASS, FAIL, PARTIAL or INCONCLUSIVE, with links to exact evidence and blocked gates.
9. Do not merge, promote, enable live payments, send messages or modify production configuration without an explicit authorized release action.

## Non-negotiable
A green build alone is not a green release. Unknown deployment identity or missing runtime evidence blocks a full release claim.
