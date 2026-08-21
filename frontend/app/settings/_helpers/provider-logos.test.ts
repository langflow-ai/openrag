import assert from "node:assert/strict";
import { readdirSync } from "node:fs";
import { join } from "node:path";
import { describe, it } from "node:test";
import { providerLogo, providerMonogram } from "./provider-logos";

const LOGO_DIR = join(process.cwd(), "public", "provider-logos");

describe("providerLogo", () => {
  it("maps direct and family provider marks", () => {
    assert.equal(providerLogo("openai"), "/provider-logos/openai_small.svg");
    assert.equal(providerLogo("anthropic"), "/provider-logos/anthropic.svg");
    assert.equal(providerLogo("bedrock_converse"), providerLogo("bedrock"));
    assert.equal(
      providerLogo("vertex_ai-mistral_models"),
      providerLogo("vertex_ai"),
    );
  });

  it("returns null for providers without a vendored mark", () => {
    assert.equal(providerLogo("nscale"), null);
    assert.equal(providerLogo("some-private-gateway"), null);
  });

  it("only returns assets that exist on disk", () => {
    const onDisk = new Set(readdirSync(LOGO_DIR));
    for (const provider of [
      "openai",
      "anthropic",
      "bedrock",
      "azure",
      "gemini",
      "mistral",
      "groq",
      "ollama",
      "watsonx",
      "deepseek",
      "openrouter",
    ]) {
      const source = providerLogo(provider);
      assert.ok(source);
      assert.equal(onDisk.has(source.replace("/provider-logos/", "")), true);
    }
  });
});

describe("providerMonogram", () => {
  it("creates stable fallback initials", () => {
    assert.equal(providerMonogram("gradient_ai"), "GA");
    assert.equal(providerMonogram("nscale"), "NS");
  });
});
