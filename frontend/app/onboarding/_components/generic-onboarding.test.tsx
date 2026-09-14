import { HttpResponse, http } from "msw";
import type { Dispatch, SetStateAction } from "react";
import { describe, expect, it } from "vitest";
import type { OnboardingVariables } from "@/app/api/mutations/useOnboardingMutation";
import { renderWithProviders, screen, userEvent } from "@/test-utils/render";
import { GenericOnboarding } from "./generic-onboarding";

const catalog = {
  providers: [
    {
      key: "azure",
      name: "Azure OpenAI",
      credential_fields: [],
      models: [{ model: "gpt-5.5", capabilities: ["function_calling"] }],
      embedding_models: [{ model: "text-embedding-3-small" }],
    },
    {
      key: "openai_like",
      name: "Other provider",
      credential_fields: [],
      models: [{ model: "gpt-4.1", capabilities: ["function_calling"] }],
      embedding_models: [],
    },
  ],
};

function renderOnboarding(provider: string, isEmbedding = false) {
  let settings: OnboardingVariables = {};
  const setSettings: Dispatch<SetStateAction<OnboardingVariables>> = (next) => {
    settings = typeof next === "function" ? next(settings) : next;
  };
  const user = userEvent.setup();
  renderWithProviders(
    <GenericOnboarding
      provider={provider}
      isEmbedding={isEmbedding}
      setSettings={setSettings}
    />,
    {
      providers: ["tooltip"],
      handlers: [
        http.get("/api/models/catalog", () => HttpResponse.json(catalog)),
      ],
    },
  );
  return { user, getSettings: () => settings };
}

describe("GenericOnboarding model selection", () => {
  it.each([
    {
      kind: "language",
      isEmbedding: false,
      selector: "language-model-selector",
      modelKey: "llm_model",
      catalogModel: "gpt-5.5",
    },
    {
      kind: "embedding",
      isEmbedding: true,
      selector: "embedding-model-selector",
      modelKey: "embedding_model",
      catalogModel: "text-embedding-3-small",
    },
  ] as const)("requires an explicit Azure $kind model choice", async (testCase) => {
    const { user, getSettings } = renderOnboarding(
      "azure",
      testCase.isEmbedding,
    );
    const selector = screen.getByTestId(testCase.selector);
    await user.click(selector);
    const catalogOption = await screen.findByRole("option", {
      name: testCase.catalogModel,
    });

    expect(selector).toHaveTextContent("Select model...");
    expect(getSettings()[testCase.modelKey]).toBeFalsy();

    await user.click(catalogOption);
    expect(getSettings()[testCase.modelKey]).toBe(testCase.catalogModel);
  });

  it("keeps automatic defaults for other generic providers", async () => {
    const { user, getSettings } = renderOnboarding("openai_like");
    await user.click(screen.getByTestId("language-model-selector"));
    await screen.findByRole("option", { name: "gpt-4.1" });
    expect(getSettings().llm_model).toBe("gpt-4.1");
  });
});
