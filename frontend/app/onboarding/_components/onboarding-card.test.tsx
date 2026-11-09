import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type { ModelProvidersResponse } from "@/app/api/queries/useGetModelProvidersQuery";
import {
  renderWithProviders,
  screen,
  userEvent,
  waitFor,
} from "@/test-utils/render";
import OnboardingCard from "./onboarding-card";

const providers: ModelProvidersResponse = {
  run_mode: "oss",
  providers: [
    { name: "openai", display_name: "OpenAI" },
    { name: "anthropic", display_name: "Anthropic" },
    { name: "rhoai", display_name: "Red Hat OpenShift AI" },
  ],
};

const catalog = {
  providers: [
    {
      key: "openai",
      name: "OpenAI",
      credential_fields: [],
      models: [{ model: "gpt-5.5", capabilities: ["function_calling"] }],
      embedding_models: [{ model: "text-embedding-3-small" }],
    },
    {
      // Serves no embedding models, and cannot discover any.
      key: "anthropic",
      name: "Anthropic",
      credential_fields: [],
      models: [{ model: "claude-sonnet-5-5" }],
      embedding_models: [],
    },
    {
      // No shipped fallback rows: the lists stay empty until the cluster is
      // asked with the credentials typed into this step.
      key: "rhoai",
      name: "Red Hat OpenShift AI",
      discovers_models: true,
      credential_fields: [
        {
          key: "api_base",
          label: "Chat endpoint",
          required: true,
          field_type: "text",
        },
        {
          key: "embedding_api_base",
          label: "Embedding endpoint",
          required: false,
          field_type: "text",
        },
        {
          key: "api_key",
          label: "Token",
          required: true,
          field_type: "password",
        },
      ],
      models: [],
      embedding_models: [],
    },
  ],
};

function renderEmbeddingStep() {
  const user = userEvent.setup();
  renderWithProviders(<OnboardingCard onComplete={() => {}} isEmbedding />, {
    providers: ["tooltip"],
    handlers: [
      http.get("/api/models/providers", () => HttpResponse.json(providers)),
      http.get("/api/models/catalog", () => HttpResponse.json(catalog)),
    ],
  });
  return { user };
}

// Until the catalogue loads every tab is shown, so the filter has only run
// once a provider without embedding models has dropped out.
async function waitForCatalogueFilter() {
  await screen.findByRole("tab", { name: /OpenAI/ });
  await waitFor(() =>
    expect(
      screen.queryByRole("tab", { name: /Anthropic/ }),
    ).not.toBeInTheDocument(),
  );
}

describe("OnboardingCard embedding step", () => {
  it("drops a provider that serves no embedding models", async () => {
    renderEmbeddingStep();

    await waitForCatalogueFilter();

    expect(screen.getByRole("tab", { name: /OpenAI/ })).toBeInTheDocument();
  });

  it("keeps a provider that discovers its models before any are listed", async () => {
    renderEmbeddingStep();

    await waitForCatalogueFilter();

    expect(
      screen.getByRole("tab", { name: /Red Hat OpenShift AI/ }),
    ).toBeInTheDocument();
  });

  it("lets the operator reach the credentials that discovery needs", async () => {
    const { user } = renderEmbeddingStep();

    await waitForCatalogueFilter();
    await user.click(screen.getByRole("tab", { name: /Red Hat OpenShift AI/ }));

    expect(
      await screen.findByRole("textbox", { name: /Chat endpoint/ }),
    ).toBeInTheDocument();
  });
});
