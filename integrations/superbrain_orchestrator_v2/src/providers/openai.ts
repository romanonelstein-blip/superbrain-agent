import { ModelProvider } from "../provider.js";
import { buildAgentInput, systemInstruction } from "../prompts.js";
import { AgentName, ProviderExecution } from "../types.js";
import { defaultFetch, env, fetchJson, FetchLike, timeoutFromEnv } from "./http.js";

export interface OpenAIProviderOptions {
  apiKey?: string;
  model?: string;
  timeoutMs?: number;
  fetchImpl?: FetchLike;
}

export class OpenAIProvider implements ModelProvider {
  readonly name = "openai" as const;
  readonly model: string;
  private readonly apiKey: string;
  private readonly timeoutMs: number;
  private readonly fetchImpl: FetchLike;

  constructor(options: OpenAIProviderOptions = {}) {
    this.apiKey = options.apiKey ?? env("OPENAI_API_KEY") ?? "";
    this.model = options.model ?? env("OPENAI_MODEL") ?? "gpt-6-astra";
    this.timeoutMs = options.timeoutMs ?? timeoutFromEnv();
    this.fetchImpl = options.fetchImpl ?? defaultFetch();

    if (!this.apiKey) throw new Error("OPENAI_API_KEY is not configured.");
  }

  async runAgent(
    agent: AgentName,
    task: string,
    context?: Record<string, unknown>
  ): Promise<ProviderExecution> {
    const { data, latencyMs, response } = await fetchJson(
      this.name,
      this.fetchImpl,
      "https://api.openai.com/v1/responses",
      {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${this.apiKey}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          model: this.model,
          instructions: systemInstruction(agent),
          input: buildAgentInput(agent, task, context)
        })
      },
      this.timeoutMs
    );

    const text = extractOpenAIText(data);
    if (!text) throw new Error("OpenAI returned no text output.");

    return {
      text,
      provider: this.name,
      model: data?.model ?? this.model,
      latencyMs,
      requestId: response.headers.get("x-request-id") ?? data?.id
    };
  }
}

export function extractOpenAIText(data: any): string {
  if (typeof data?.output_text === "string" && data.output_text.trim()) {
    return data.output_text.trim();
  }

  const chunks: string[] = [];
  for (const item of data?.output ?? []) {
    if (item?.type !== "message") continue;
    for (const content of item?.content ?? []) {
      if (content?.type === "output_text" && typeof content?.text === "string") {
        chunks.push(content.text);
      }
    }
  }
  return chunks.join("\n").trim();
}
