import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ConsoleStatusButton } from "./button";

vi.mock("@/hooks/use-narrow-layout", () => ({
  useNarrowLayout: vi.fn().mockReturnValue(false),
}));

import { useNarrowLayout } from "@/hooks/use-narrow-layout";

describe("ConsoleStatusButton", () => {
  it("renders in wide mode and handles clicks", async () => {
    const user = userEvent.setup();
    const handleClick = vi.fn();

    render(
      <ConsoleStatusButton
        onClick={handleClick}
        isOpen={false}
        overallStatus="healthy"
      />,
    );

    const button = screen.getByRole("button", { name: "Console Status" });
    expect(button).toBeInTheDocument();
    expect(screen.getByText("Console Status")).toBeInTheDocument();

    await user.click(button);
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it("renders in narrow mode with unhealthy status dot", () => {
    vi.mocked(useNarrowLayout).mockReturnValue(true);

    render(
      <ConsoleStatusButton
        onClick={() => {}}
        isOpen={true}
        overallStatus="unhealthy"
      />,
    );

    const button = screen.getByRole("button", { name: "Console Status" });
    expect(button).toBeInTheDocument();
    expect(screen.queryByText("Console Status")).not.toBeInTheDocument();
  });
});
