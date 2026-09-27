import { buildAgentInput, systemInstruction } from "../prompts.js";
import { defaultFetch, env, fetchJson, timeoutFromEnv } from "./http.js";
export class GeminiProvider {
    name = "gemini";
    model;
    apiKey;
    timeoutMs;
    fetchImpl;
    constructor(options = {}) {
        this.apiKey = options.apiKey ?? env("GEMINI_API_KEY") ?? "";
        this.model = options.model ?? env("GEMINI_MODEL") ?? "gemini-3.8-flash";
        this.timeoutMs = options.timeoutMs ?? timeoutFromEnv();
        this.fetchImpl = options.fetchImpl ?? defaultFetch();
        if (!this.apiKey)
            throw new Error("GEMINI_API_KEY is not configured.");
    }
    async runAgent(agent, task, context) {
        // The Interactions API has a unified `input` primitive. To keep the provider
        // contract identical across vendors, Superbrain folds the role instruction
        // into the text input rather than depending on vendor-specific prompt fields.
        const input = [
            systemInstruction(agent),
            "",
            buildAgentInput(agent, task, context)
        ].join("\n");
        const { data, latencyMs, response } = await fetchJson(this.name, this.fetchImpl, "https://generativelanguage.googleapis.com/v1/interactions", {
            method: "POST",
            headers: {
                "x-goog-api-key": this.apiKey,
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                model: this.model,
                input
            })
        }, this.timeoutMs);
        const text = extractGeminiText(data);
        if (!text)
            throw new Error("Gemini returned no text output.");
        return {
            text,
            provider: this.name,
            model: data?.model ?? this.model,
            latencyMs,
            requestId: response.headers.get("x-request-id") ?? data?.id
        };
    }
}
export function extractGeminiText(data) {
    const chunks = [];
    for (const step of data?.steps ?? []) {
        if (step?.type !== "model_output")
            continue;
        for (const content of step?.content ?? []) {
            if (content?.type === "text" && typeof content?.text === "string") {
                chunks.push(content.text);
            }
        }
    }
    return chunks.join("\n").trim();
}
