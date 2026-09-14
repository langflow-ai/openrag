import { describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { renderWithProviders, screen, userEvent } from "@/test-utils/render";
import { AdvancedOnboarding } from "./advanced";

describe("AdvancedOnboarding custom models", () => {
  it("accepts a language model that is absent from provider inventory", async () => {
    const setLanguageModel = vi.fn();
    const user = userEvent.setup();

    renderWithProviders(
      <TooltipProvider>
        <AdvancedOnboarding
          languageModels={[]}
          languageModel=""
          setLanguageModel={setLanguageModel}
        />
      </TooltipProvider>,
    );

    const selector = screen.getByTestId("language-model-selector");
    expect(selector).toBeEnabled();
    await user.click(selector);
    await user.type(
      screen.getByTestId("model-search-input"),
      "acme/private-model",
    );
    await user.click(
      screen.getByTestId("model-custom-option-acme/private-model"),
    );

    expect(setLanguageModel).toHaveBeenCalledWith("acme/private-model");
  });

  it("accepts an embedding model that is absent from provider inventory", async () => {
    const setEmbeddingModel = vi.fn();
    const user = userEvent.setup();

    renderWithProviders(
      <TooltipProvider>
        <AdvancedOnboarding
          embeddingModels={[]}
          embeddingModel=""
          setEmbeddingModel={setEmbeddingModel}
        />
      </TooltipProvider>,
    );

    const selector = screen.getByTestId("embedding-model-selector");
    expect(selector).toBeEnabled();
    await user.click(selector);
    await user.type(
      screen.getByTestId("model-search-input"),
      "acme/private-embedding",
    );
    await user.click(
      screen.getByTestId("model-custom-option-acme/private-embedding"),
    );

    expect(setEmbeddingModel).toHaveBeenCalledWith("acme/private-embedding");
  });
});
