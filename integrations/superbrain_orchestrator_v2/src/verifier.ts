import { AgentResult, VerificationResult } from "./types.js";

export function verifyResults(results: AgentResult[]): VerificationResult {
  const core = results.filter(r => !["critic", "verifier"].includes(r.agent));
  const issues: string[] = [];

  if (!core.length) issues.push("No substantive specialist output.");
  if (core.some(r => !r.output || r.output.trim().length < 10)) {
    issues.push("One or more agent outputs are too thin.");
  }

  const verified = issues.length === 0;
  const confidence = verified
    ? Math.min(0.95, 0.72 + core.length * 0.05)
    : 0.45;

  return { verified, confidence, issues };
}
