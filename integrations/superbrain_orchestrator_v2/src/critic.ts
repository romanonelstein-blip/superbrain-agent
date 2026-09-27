import { AgentResult } from "./types.js";

export function findDisagreements(results: AgentResult[]): string[] {
  const substantive = results.filter(r => !["critic", "verifier"].includes(r.agent));
  if (substantive.length < 2) return [];

  // v1 deterministic placeholder: detect strongly different answer lengths
  const lengths = substantive.map(r => r.output.length);
  const max = Math.max(...lengths);
  const min = Math.min(...lengths);

  return max > min * 3
    ? ["Agent outputs differ substantially in scope; synthesis should reconcile them."]
    : [];
}
