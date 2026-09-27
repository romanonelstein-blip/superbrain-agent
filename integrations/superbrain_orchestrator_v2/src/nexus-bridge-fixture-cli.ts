import { ModelProvider } from "./provider.js";
import { runNexusProviderMission } from "./nexus-bridge.js";
import { ProviderRouter } from "./providers/router.js";
import { AgentName, OrchestrationRequest, ProviderExecution } from "./types.js";

function fixtureProvider(
  name: "gemini" | "openai",
  shouldFail: boolean
): ModelProvider {
  return {
    name,
    model: `${name}-sb016-fixture`,
    async runAgent(agent: AgentName): Promise<ProviderExecution> {
      if (shouldFail) throw new Error(`${name} fixture unavailable`);
      return {
        text: "The launch has validated demand.",
        provider: name,
        model: `${name}-sb016-fixture`,
        latencyMs: 7,
        requestId: `sb016-${agent}`
      };
    }
  };
}

async function readInput(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) chunks.push(Buffer.from(chunk));
  return Buffer.concat(chunks).toString("utf8");
}

async function main(): Promise<void> {
  const request = JSON.parse(await readInput()) as OrchestrationRequest;
  if (!request.task || typeof request.task !== "string") {
    throw new Error("A non-empty task string is required.");
  }
  const router = new ProviderRouter(
    [fixtureProvider("gemini", true), fixtureProvider("openai", false)],
    { research: ["gemini", "openai"] }
  );
  const result = await runNexusProviderMission(router, request);
  process.stdout.write(JSON.stringify({ ...result, fixture: true }));
}

main().catch(error => {
  const message = error instanceof Error ? error.message : String(error);
  process.stderr.write(`SB-016 fixture bridge failed: ${message}\n`);
  process.exitCode = 1;
});
