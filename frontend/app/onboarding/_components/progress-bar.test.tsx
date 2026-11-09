import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ProgressBar } from "./progress-bar";

vi.mock("@/lib/analytics", () => ({
  trackButton: vi.fn(),
}));

describe("ProgressBar", () => {
  it("renders progress bar and handles skip overview click", async () => {
    const user = userEvent.setup();
    const handleSkip = vi.fn();

    render(<ProgressBar currentStep={2} totalSteps={5} onSkip={handleSkip} />);

    expect(screen.getByText("3/5")).toBeInTheDocument();
    const skipButton = screen.getByTestId("skip-overview-button");
    expect(skipButton).toBeInTheDocument();

    await user.click(skipButton);
    expect(handleSkip).toHaveBeenCalledTimes(1);
  });
});
