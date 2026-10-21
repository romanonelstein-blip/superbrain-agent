# Security policy

## Scope

Security reports for SuperBrain Agent, including the NEXUS bridge, GitHub workflows, and local agent execution, are welcome.

## Responsible disclosure

Please do **not** publish working exploit details, passwords, API keys, tokens, or confidential logs in a public issue or pull request. Use GitHub's private vulnerability reporting option if available on this repository. If it is unavailable, open a public issue requesting a private contact channel **without** including sensitive details.

We will triage reproducible, responsibly reported issues and provide updates through the reporting channel. No specific response time or security certification is promised.

## Handling secrets

Store credentials only in GitHub Actions secrets or an appropriate local secret manager; never commit `.env` files or credentials to source control. If a credential is exposed, revoke/rotate it at its provider, and then assess history and logs. Removing it from the latest commit does not make the old credential safe.

Automated scans are defenses in depth and do not guarantee that every secret or vulnerability is detected.
