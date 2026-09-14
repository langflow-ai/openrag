import { describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, userEvent } from "@/test-utils/render";
import { ModelSelector } from "./model-selector";

describe("ModelSelector custom entries", () => {
  it("offers a typed model under every configured provider group", async () => {
    const onValueChange = vi.fn();
    const user = userEvent.setup();

    renderWithProviders(
      <ModelSelector
        groupedOptions={[
          {
            group: "OpenAI",
            provider: "openai",
            options: [{ value: "gpt-4o", label: "gpt-4o" }],
          },
          {
            group: "Anthropic",
            provider: "anthropic",
            options: [{ value: "claude-sonnet-4", label: "Claude Sonnet 4" }],
          },
        ]}
        custom
        value=""
        onValueChange={onValueChange}
        defaultOpen
      />,
    );

    await user.type(
      screen.getByTestId("model-search-input"),
      "acme/private-model",
    );

    expect(
      screen.getByRole("option", {
        name: "Use openai:acme/private-model",
      }),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("option", {
        name: "Use anthropic:acme/private-model",
      }),
    );

    expect(onValueChange).toHaveBeenCalledWith(
      "acme/private-model",
      "anthropic",
    );
  });
});
