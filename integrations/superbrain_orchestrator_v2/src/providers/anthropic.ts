import { ModelProvider } from "../provider.js";
import { buildAgentInput, systemInstruction } from "../prompts.js";
import { AgentName, ProviderExecution } from "../types.js";
import { defaultFetch, env, fetchJson, FetchLike, timeoutFromEnv } from "./http.js";

export interface AnthropicProviderOptions {
  apiKey?: string;
  model?: string;
  maxTokens?: number;
  timeoutMs?: number;
  fetchImpl?: FetchLike;
}

export class AnthropicProvider implements ModelProvider {
  readonly name = "anthropic" as const;
  readonly model: string;
  private readonly apiKey: string;
  private readonly maxTokens: number;
  private readonly timeoutMs: number;
  private readonly fetchImpl: FetchLike;

  constructor(options: AnthropicProviderOptions = {}) {
    this.apiKey = options.apiKey ?? env("ANTHROPIC_API_KEY") ?? "";
    this.model = options.model ?? env("ANTHROPIC_MODEL") ?? "claude-sonnet-5";
    this.maxTokens = options.maxTokens ?? 4096;
    this.timeoutMs = options.timeoutMs ?? timeoutFromEnv();
    this.fetchImpl = options.fetchImpl ?? defaultFetch();

    if (!this.apiKey) throw new Error("ANTHROPIC_API_KEY is not configured.");
  }

  async runAgent(
    agent: AgentName,
    task: string,
    context?: Record<string, unknown>
  ): Promise<ProviderExecution> {
    const { data, latencyMs, response } = await fetchJson(
      this.name,
      this.fetchImpl,
      "https://api.anthropic.com/v1/messages",
      {
        method: "POST",
        headers: {
          "x-api-key": this.apiKey,
          "anthropic-version": "2023-06-01",
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          model: this.model,
          max_tokens: this.maxTokens,
          system: systemInstruction(agent),
          messages: [
            {
              role: "user",
              content: buildAgentInput(agent, task, context)
            }
          ]
        })
      },
      this.timeoutMs
    );

    const text = (data?.content ?? [])
      .filter((block: any) => block?.type === "text" && typeof block?.text === "string")
      .map((block: any) => block.text)
      .join("\n")
      .trim();

    if (!text) throw new Error("Anthropic returned no text output.");

    return {
      text,
      provider: this.name,
      model: data?.model ?? this.model,
      latencyMs,
      requestId: response.headers.get("request-id") ?? data?.id
    };
  }
}
