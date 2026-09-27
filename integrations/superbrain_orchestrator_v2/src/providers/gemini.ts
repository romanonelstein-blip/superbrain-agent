import { ModelProvider } from "../provider.js";
import { buildAgentInput, systemInstruction } from "../prompts.js";
import { AgentName, ProviderExecution } from "../types.js";
import { defaultFetch, env, fetchJson, FetchLike, timeoutFromEnv } from "./http.js";

export interface GeminiProviderOptions {
  apiKey?: string;
  model?: string;
  timeoutMs?: number;
  fetchImpl?: FetchLike;
}

export class GeminiProvider implements ModelProvider {
  readonly name = "gemini" as const;
  readonly model: string;
  private readonly apiKey: string;
  private readonly timeoutMs: number;
  private readonly fetchImpl: FetchLike;

  constructor(options: GeminiProviderOptions = {}) {
    this.apiKey = options.apiKey ?? env("GEMINI_API_KEY") ?? "";
    this.model = options.model ?? env("GEMINI_MODEL") ?? "gemini-3.8-flash";
    this.timeoutMs = options.timeoutMs ?? timeoutFromEnv();
    this.fetchImpl = options.fetchImpl ?? defaultFetch();

    if (!this.apiKey) throw new Error("GEMINI_API_KEY is not configured.");
  }

  async runAgent(
    agent: AgentName,
    task: string,
    context?: Record<string, unknown>
  ): Promise<ProviderExecution> {
    // The Interactions API has a unified `input` primitive. To keep the provider
    // contract identical across vendors, Superbrain folds the role instruction
    // into the text input rather than depending on vendor-specific prompt fields.
    const input = [
      systemInstruction(agent),
      "",
      buildAgentInput(agent, task, context)
    ].join("\n");

    const { data, latencyMs, response } = await fetchJson(
      this.name,
      this.fetchImpl,
      "https://generativelanguage.googleapis.com/v1/interactions",
      {
        method: "POST",
        headers: {
          "x-goog-api-key": this.apiKey,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          model: this.model,
          input
        })
      },
      this.timeoutMs
    );

    const text = extractGeminiText(data);
    if (!text) throw new Error("Gemini returned no text output.");

    return {
      text,
      provider: this.name,
      model: data?.model ?? this.model,
      latencyMs,
      requestId: response.headers.get("x-request-id") ?? data?.id
    };
  }
}

export function extractGeminiText(data: any): string {
  const chunks: string[] = [];
  for (const step of data?.steps ?? []) {
    if (step?.type !== "model_output") continue;
    for (const content of step?.content ?? []) {
      if (content?.type === "text" && typeof content?.text === "string") {
        chunks.push(content.text);
      }
    }
  }
  return chunks.join("\n").trim();
}
