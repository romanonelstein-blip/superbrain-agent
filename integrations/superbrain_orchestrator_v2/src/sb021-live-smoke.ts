import { AnthropicProvider } from "./providers/anthropic.js";
import { GeminiProvider } from "./providers/gemini.js";
import { env } from "./providers/http.js";
import { OpenAIProvider } from "./providers/openai.js";
import { classifyProviderFailure } from "./providers/resilience.js";
import { ModelProvider } from "./provider.js";

interface SmokeResult {
  provider: string;
  model: string;
  attempted: boolean;
  success: boolean;
  latencyMs?: number;
  failureKind?: string;
}

async function main(): Promise<void> {
  if (env("SUPERBRAIN_LIVE_PROVIDER_SMOKE") !== "1") {
    process.stdout.write(JSON.stringify({ liveSmoke: "skipped", reason: "opt_in_required" }, null, 2) + "\n");
    return;
  }

  const providers: ModelProvider[] = [];
  if (env("OPENAI_API_KEY")) providers.push(new OpenAIProvider({ timeoutMs: 15_000 }));
  if (env("ANTHROPIC_API_KEY")) providers.push(new AnthropicProvider({ timeoutMs: 15_000, maxTokens: 32 }));
  if (env("GEMINI_API_KEY")) providers.push(new GeminiProvider({ timeoutMs: 15_000 }));

  if (!providers.length) {
    process.stdout.write(JSON.stringify({ liveSmoke: "skipped", reason: "no_credentials" }, null, 2) + "\n");
    return;
  }

  const results: SmokeResult[] = [];
  for (const provider of providers) {
    try {
      const execution = await provider.runAgent("verifier", "Reply with exactly: OK");
      results.push({
        provider: provider.name,
        model: execution.model,
        attempted: true,
        success: Boolean(execution.text.trim()),
        latencyMs: execution.latencyMs
      });
    } catch (error) {
      const failure = classifyProviderFailure(error);
      results.push({
        provider: provider.name,
        model: provider.model,
        attempted: true,
        success: false,
        failureKind: failure.kind
      });
    }
  }

  process.stdout.write(JSON.stringify({ liveSmoke: "completed", results }, null, 2) + "\n");
  if (results.some(result => !result.success)) process.exitCode = 1;
}

main().catch(() => {
  process.stderr.write("Live provider smoke failed safely.\n");
  process.exitCode = 1;
});
