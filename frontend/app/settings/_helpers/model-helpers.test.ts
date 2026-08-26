/**
 * Provider ordering and chrome.
 *
 * Which providers exist is the backend's call (config/model_providers.yaml
 * filtered by OPENRAG_RUN_MODE); the frontend only decides what order to show
 * them in and what to call them. These pin that a provider the backend adds
 * still renders, and that a hidden one can never be re-introduced by the
 * preference lists.
 */

import assert from "node:assert/strict";
import { describe, it } from "node:test";
import {
  EMBEDDING_PROVIDER_ORDER,
  getProviderChrome,
  LLM_PROVIDER_ORDER,
  orderProviders,
} from "./model-helpers";

describe("orderProviders", () => {
  it("ranks preferred providers first and keeps the rest in API order", () => {
    assert.deepEqual(
      orderProviders(
        ["openai", "watsonx", "azure_ai", "anthropic"],
        ["anthropic", "openai"],
      ),
      ["anthropic", "openai", "watsonx", "azure_ai"],
    );
  });

  it("never adds a provider the backend did not offer", () => {
    // SaaS hides Ollama, so no preference list may put it back.
    assert.deepEqual(
      orderProviders(["openai", "watsonx"], LLM_PROVIDER_ORDER),
      ["openai", "watsonx"],
    );
    assert.deepEqual(orderProviders(["openai"], EMBEDDING_PROVIDER_ORDER), [
      "openai",
    ]);
  });

  it("keeps a provider that no preference list mentions", () => {
    assert.deepEqual(orderProviders(["azure_ai"], LLM_PROVIDER_ORDER), [
      "azure_ai",
    ]);
  });
});

describe("getProviderChrome", () => {
  it("names an unknown provider by its API display name", () => {
    assert.equal(getProviderChrome("groq", "Groq Cloud").name, "Groq Cloud");
  });

  it("falls back to the provider key when the API sent no name", () => {
    assert.equal(getProviderChrome("groq").name, "groq");
  });

  it("lets the API display name override a built-in label", () => {
    assert.equal(getProviderChrome("openai").name, "OpenAI");
    assert.equal(
      getProviderChrome("openai", "House Gateway").name,
      "House Gateway",
    );
  });

  it("gives Azure AI its own chrome", () => {
    const azure = getProviderChrome("azure_ai");
    assert.equal(azure.name, "Azure AI Foundry");
    assert.notEqual(azure.logo, getProviderChrome("groq").logo);
  });
});
