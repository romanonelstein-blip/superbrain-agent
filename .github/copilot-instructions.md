# Copilot Instructions for Superbrain Agent

This file provides guidance for GitHub Copilot when working on the Superbrain Agent repository.

## Project Overview

**Superbrain Agent** is an open-source engineering agent for secure, local Git/GitHub CLI workflows with Ollama/Codex integration.

**Core Philosophy:**
- 🔒 Privacy-first: Code stays local by default
- 🔍 Transparent: Every action is logged and auditable
- ✅ Safe: Dangerous operations require explicit approval
- 🚀 Local: Uses local tools (Git, Ollama) whenever possible
- 🤝 Open-source: No proprietary code or hidden operations

## Architecture & Modules

### `/src/core/` - Core Infrastructure
- **git.ts** - Git operations wrapper (read-only repository diagnostics)
- **github.ts** - GitHub CLI integration & authentication status
- **capability-registry.ts** - Tool detection and versioning

### `/src/audit/` - Logging & Compliance
- **audit-log.ts** - Append-only audit logging system (JSON Lines format)

### `/src/workflow/` - Workflow Management
- **approval-engine.ts** - Approval workflow for dangerous operations
- **test-runner.ts** - *Coming soon* - Auto-detect & run tests
- **preview-server.ts** - *Coming soon* - Local preview management

### `/src/providers/` - Tool Integrations
- **ollama-provider.ts** - *Coming soon* - Local AI via Ollama
- **codex-provider.ts** - *Coming soon* - External AI fallback

### `/src/types/` - Type Definitions
- **index.ts** - Complete TypeScript interfaces for all data structures

## Key Principles for Code Contributions

### 1. Read-Only by Default
When working with Git or file operations, assume read-only unless explicitly required for the workflow:
```typescript
// ✅ Good: Read-only diagnosis
const repoInfo = await git.getRepositoryInfo(path);
console.log(repoInfo.modifiedFiles);

// ❌ Bad: Modifying without approval
await execa('git', ['add', '.']);
```

### 2. Explicit Approval for Dangerous Operations
Dangerous operations (push, merge, delete, deploy, etc.) MUST go through the ApprovalEngine:
```typescript
// ✅ Good: Request approval first
const result = await approvalEngine.requestApproval(
  'op-123',
  'push',
  'Pushing changes to main branch'
);

if (result.status === 'approval_needed') {
  // Wait for user approval
}

// ❌ Bad: Direct execution without approval
await execa('git', ['push', 'origin', 'main']);
```

### 3. Audit Every Action
All meaningful actions must be logged:
```typescript
// ✅ Good: Log all actions
auditLog.log({
  timestamp: new Date(),
  repository: 'my-repo',
  branch: 'main',
  user: 'developer@example.com',
  tool: 'git',
  command: 'status',
  modifiedFiles: [],
  approved: true,
  risks: []
});
```

### 4. Clear Error Messages
Never show generic errors. Always explain what's wrong and suggest next steps:
```typescript
// ✅ Good: Detailed error context
throw new Error(
  'GitHub CLI is not installed. Install from: https://cli.github.com ' +
  'Then authenticate with: gh auth login'
);

// ❌ Bad: Generic error
throw new Error('CLI error');
```

### 5. Privacy & Security
- Never log sensitive data (tokens, passwords, keys)
- Always validate TLS certificates
- Never auto-fill credentials
- Always ask for confirmation before external calls
- Use local tools (Ollama) before external ones (Codex)

### 6. Tool Detection Pattern
Use CapabilityRegistry to check tool availability:
```typescript
// ✅ Good: Check capability before use
const caps = await capabilityRegistry.getCapabilities();
if (caps.ollama.available) {
  // Use local Ollama
} else {
  console.warn('Ollama not available. Install from: https://ollama.ai');
}
```

### 7. No Hardcoded Paths or Secrets
```typescript
// ✅ Good: Use environment variables
const repoPath = process.env.SUPERBRAIN_REPO_PATH || '.';

// ✅ Good: Accept as parameter
constructor(repositoryPath: string) { }

// ❌ Bad: Hardcoded paths
const repoPath = '/Users/developer/repo';

// ❌ Bad: Hardcoded secrets
const token = 'ghp_xxxxxxxxxxxx';
```

## Type Safety

Always use the provided TypeScript interfaces:

```typescript
import type {
  RepositoryInfo,
  GitHubCliStatus,
  ToolCapability,
  CapabilityRegistry,
  AuditLogEntry,
  ActionStatus,
  ActionResult
} from '../types/index.js';
```

## Testing Requirements

All new features must include tests:

```typescript
// ✅ Required: Unit test for new feature
describe('MyFeature', () => {
  test('should do X when Y', () => {
    // Test implementation
  });

  test('should handle error case', () => {
    // Error handling test
  });
});
```

Run tests before committing:
```bash
npm test
npm run test:coverage
```

## Documentation Requirements

- Add JSDoc comments to all public methods
- Update `/docs/` when adding features
- Include examples for complex operations
- Document all configuration options

## Git Commit Guidelines

Use clear, descriptive commit messages:

```
✅ GOOD:
- fix: handle missing GitHub CLI gracefully with helpful error message
- feat: add Ollama provider with fallback to Codex
- docs: update security guide with TLS validation details
- test: add audit log entry validation tests

❌ AVOID:
- Fixed bug
- Updated code
- Work in progress
```

## PR Review Checklist

Before submitting a PR, ensure:
- [ ] Code follows the principles above
- [ ] All tests pass (`npm test`)
- [ ] No hardcoded secrets or sensitive data
- [ ] Error messages are helpful and actionable
- [ ] Audit logging is implemented
- [ ] Documentation is updated
- [ ] Approval workflow is used for dangerous ops
- [ ] Privacy is maintained (no external calls without consent)

## Useful Commands

```bash
# Build TypeScript
npm run build

# Run tests with coverage
npm run test:coverage

# Lint code
npm run lint

# Watch mode for development
npm run dev

# Build & run all checks
npm run build && npm test && npm run lint
```

## Security Checklist for Code Review

- ❌ No `eval()` or `Function()` constructor
- ❌ No cleartext passwords or tokens
- ❌ No disabled TLS validation
- ❌ No `exec()` with unsanitized input
- ❌ No automatic credential filling
- ❌ No external API calls without approval
- ✅ All dangerous operations go through ApprovalEngine
- ✅ All actions are logged to AuditLog
- ✅ Error messages are descriptive

## Resources

- **GitHub Copilot Docs:** https://copilot.github.com/
- **TypeScript Handbook:** https://www.typescriptlang.org/docs/
- **GitHub CLI Docs:** https://cli.github.com/
- **Ollama Docs:** https://ollama.ai/
- **Security Best Practices:** https://cheatsheetseries.owasp.org/

## Questions or Issues?

If you're unsure about implementation:
1. Check the acceptance criteria in `.github/superbrain-workflow-prompt.md`
2. Review similar implementations in existing code
3. Look at the type definitions in `src/types/index.ts`
4. Read the security guide at `docs/SECURITY.md`

---

**Remember:** When in doubt, favor transparency, security, and local execution over convenience.
