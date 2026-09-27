# GitHub authentication diagnostics

`GitHubCliProvider.getAuthStatus()` runs `gh auth status` without requesting a token.
It supports login metadata on stdout and stderr, including modern `account` and
legacy `as` output. Unknown output and nonzero exits do not claim a verified login.
CLI detection has a 5-second timeout; authentication checks have a 10-second timeout.
Raw CLI errors are not returned because they can contain sensitive output.

No login or credential changes are performed. When authentication cannot be
confirmed, the user is directed to `gh auth status` and `gh auth login`.
With multiple reported accounts, `username` is the first reported account and
`activeHosts` contains the distinct hosts with reported successful logins; this
is not a guarantee that every account on every host is healthy.

Run `npm test` for the build, existing Jest tests and authentication regression
tests. `npm run test:github` runs only the build and authentication regression
checks. The latter use an isolated fake CLI on POSIX systems and do not contact
GitHub or read real credentials. `npm run lint` checks all TypeScript sources.
