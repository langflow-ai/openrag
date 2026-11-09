import { describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { renderWithProviders, screen, userEvent } from "@/test-utils/render";
import { AdvancedOnboarding } from "./advanced";

describe("AdvancedOnboarding custom models", () => {
  it("previews five models, exposes the full list, and explains Azure search", async () => {
    const user = userEvent.setup();
    const models = [
      ...Array.from({ length: 5 }, (_, index) => ({
        value: `gpt-5-${index}`,
        label: `gpt-5-${index}`,
      })),
      { value: "gpt-4.1", label: "gpt-4.1" },
    ];

    renderWithProviders(
      <TooltipProvider>
        <AdvancedOnboarding
          languageModels={models}
          languageModel="gpt-5-0"
          setLanguageModel={vi.fn()}
          searchPlaceholder="Search models or type Azure deployment name"
        />
      </TooltipProvider>,
    );

    await user.click(screen.getByTestId("language-model-selector"));
    expect(
      screen.getByPlaceholderText(
        "Search models or type Azure deployment name",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "gpt-4.1" })).toBeNull();
    await user.click(screen.getByRole("option", { name: "Show all 6 models" }));
    expect(screen.getByRole("option", { name: "gpt-4.1" })).toBeInTheDocument();
  });

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
