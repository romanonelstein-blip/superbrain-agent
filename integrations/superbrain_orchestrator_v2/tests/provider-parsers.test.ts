import { describe, expect, it } from "./testkit.js";
import { extractOpenAIText } from "../src/providers/openai.js";
import { extractGeminiText } from "../src/providers/gemini.js";

describe("provider response parsing", () => {
  it("extracts OpenAI Responses API text", () => {
    expect(extractOpenAIText({
      output: [{
        type: "message",
        content: [{ type: "output_text", text: "hello" }]
      }]
    })).toBe("hello");
  });

  it("extracts Gemini Interactions API model output", () => {
    expect(extractGeminiText({
      steps: [{
        type: "model_output",
        content: [{ type: "text", text: "hello" }]
      }]
    })).toBe("hello");
  });
});
