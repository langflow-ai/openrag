import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { LowRelevanceBanner } from "./low-relevance-banner";

function setup(showingAll: boolean) {
  const onToggle = vi.fn();
  render(
    <LowRelevanceBanner
      showingAll={showingAll}
      hiddenMessage="3 files hidden"
      shownMessage="Showing everything"
      onToggle={onToggle}
    />,
  );
  return { onToggle };
}

describe("LowRelevanceBanner", () => {
  it("shows the hidden message and a 'Show all' action while collapsed", () => {
    setup(false);

    expect(screen.getByText("3 files hidden")).toBeInTheDocument();
    expect(screen.getByText("Show all")).toBeInTheDocument();
    expect(screen.queryByText("Showing everything")).not.toBeInTheDocument();
    expect(screen.queryByText("Hide low-relevance")).not.toBeInTheDocument();
  });

  it("shows the shown message and a 'Hide low-relevance' action while expanded", () => {
    setup(true);

    expect(screen.getByText("Showing everything")).toBeInTheDocument();
    expect(screen.getByText("Hide low-relevance")).toBeInTheDocument();
    expect(screen.queryByText("3 files hidden")).not.toBeInTheDocument();
    expect(screen.queryByText("Show all")).not.toBeInTheDocument();
  });

  it("calls onToggle when clicked", async () => {
    const { onToggle } = setup(false);

    await userEvent.click(screen.getByRole("button"));

    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
