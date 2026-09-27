import { AgentName, Complexity, OrchestrationRequest } from "./types.js";

const HIGH_COMPLEXITY_MARKERS = [
  "strategy", "architecture", "build", "implement", "financial",
  "business", "research", "compare", "investigate", "plan"
];

export function classifyComplexity(task: string): Complexity {
  const normalized = task.toLowerCase();
  const markerHits = HIGH_COMPLEXITY_MARKERS.filter(m => normalized.includes(m)).length;

  if (task.length > 700 || markerHits >= 4) return "high";
  if (task.length > 220 || markerHits >= 2) return "medium";
  return "low";
}

export function routeAgents(request: OrchestrationRequest): AgentName[] {
  if (request.preferredAgents?.length) {
    return Array.from(new Set([...request.preferredAgents, "critic", "verifier"]));
  }

  const task = request.task.toLowerCase();
  const agents: AgentName[] = [];

  if (/research|find|investigate|compare|evidence/.test(task)) agents.push("research");
  if (/strategy|plan|position|roadmap|decision/.test(task)) agents.push("strategy");
  if (/build|code|implement|technical|architecture/.test(task)) agents.push("builder");
  if (/business|revenue|customer|market|sales/.test(task)) agents.push("business");
  if (/finance|cost|margin|profit|budget|roi/.test(task)) agents.push("finance");

  if (!agents.length) agents.push("strategy");

  const complexity = classifyComplexity(request.task);
  if (complexity === "high" && !agents.includes("research")) agents.push("research");

  agents.push("critic", "verifier");
  return Array.from(new Set(agents));
}
