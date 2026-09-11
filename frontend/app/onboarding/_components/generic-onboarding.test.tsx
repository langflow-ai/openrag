import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { GenericOnboarding } from "./generic-onboarding";

vi.mock("@/app/api/queries/useGetModelsQuery", () => ({
  useGetModelCatalogQuery: vi.fn().mockReturnValue({
    data: {
      providers: [
        {
          key: "openai",
          models: [{ model: "gpt-4o" }, { model: "gpt-4o-mini" }],
          embedding_models: [
            { model: "text-embedding-3-small" },
            { model: "text-embedding-3-large" },
          ],
        },
      ],
    },
  }),
}));

vi.mock("@/components/models/model-selector", () => ({
  ModelSelector: ({ value, onValueChange, options = [] }: any) => (
    <select
      data-testid="model-selector"
      value={value}
      onChange={(e) => onValueChange?.(e.target.value)}
    >
      {options.map((m: any) => (
        <option key={m.value} value={m.value}>
          {m.label}
        </option>
      ))}
    </select>
  ),
}));

describe("GenericOnboarding", () => {
  it("seeds credentials and synchronizes parent settings", async () => {
    const user = userEvent.setup();
    const mockSetSettings = vi.fn();

    render(
      <TooltipProvider>
        <GenericOnboarding
          provider="openai"
          isEmbedding={false}
          setSettings={mockSetSettings}
          savedValues={{ api_key: "sk-test" }}
          providers={{ custom: {} } as any}
        />
      </TooltipProvider>,
    );

    expect(mockSetSettings).toHaveBeenCalled();

    // Check input change
    const apiKeyInput = screen.getByLabelText(/API Key/i);
    await user.clear(apiKeyInput);
    await user.type(apiKeyInput, "sk-new-key");

    expect(mockSetSettings).toHaveBeenCalled();
  });

  it("handles embedding mode and model selection", async () => {
    const user = userEvent.setup();
    const mockSetSettings = vi.fn();

    render(
      <TooltipProvider>
        <GenericOnboarding
          provider="openai"
          isEmbedding={true}
          setSettings={mockSetSettings}
          savedValues={{}}
          providers={{ custom: {} } as any}
        />
      </TooltipProvider>,
    );

    expect(mockSetSettings).toHaveBeenCalled();

    const selector = screen.getByTestId("model-selector");
    await user.selectOptions(selector, "text-embedding-3-large");
    expect(mockSetSettings).toHaveBeenCalled();
  });
});
