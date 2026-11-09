import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import Nudges from "./nudges";

describe("Nudges", () => {
  it("renders suggestions and handles clicks", async () => {
    const user = userEvent.setup();
    const handleClick = vi.fn();
    const suggestions = ["Suggestion 1", "Suggestion 2"];

    render(
      <Nudges
        nudges={suggestions}
        onboarding={false}
        handleSuggestionClick={handleClick}
      />,
    );

    const firstSuggestion = screen.getByTestId("suggestion-0");
    expect(firstSuggestion).toBeInTheDocument();
    expect(firstSuggestion).toHaveTextContent("Suggestion 1");

    await user.click(firstSuggestion);
    expect(handleClick).toHaveBeenCalledWith("Suggestion 1");
  });

  it("renders with onboarding theme classes", () => {
    const suggestions = ["Nudge A"];
    render(
      <Nudges
        nudges={suggestions}
        onboarding={true}
        handleSuggestionClick={() => {}}
      />,
    );

    const button = screen.getByTestId("suggestion-0");
    expect(button.className).toContain("text-foreground");
  });
});
