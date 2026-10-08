import { act, fireEvent } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithProviders, screen } from "@/test-utils/render";
import { KnowledgeDateRangeFilter } from "./knowledge-date-range-filter";

// Radix Popover ignores userEvent pointer sequences in JSDOM; fireEvent.click opens it.
// Button title-cases string children, hence the case-insensitive matchers.
async function click(el: HTMLElement) {
  await act(async () => {
    fireEvent.click(el);
  });
}

function renderFilter() {
  renderWithProviders(<KnowledgeDateRangeFilter />, {
    providers: ["knowledgeFilter"],
  });
}

async function openPopover() {
  await click(screen.getByRole("button", { name: /filter by date range/i }));
}

describe("KnowledgeDateRangeFilter", () => {
  it("renders the trigger with the default label", () => {
    renderFilter();
    expect(
      screen.getByRole("button", { name: /filter by date range/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("Date range")).toBeInTheDocument();
  });

  it("shows presets when opened", async () => {
    renderFilter();
    await openPopover();
    expect(screen.getByText(/last 7 days/i)).toBeInTheDocument();
    expect(screen.getByText(/last 30 days/i)).toBeInTheDocument();
    expect(screen.getByText(/this month/i)).toBeInTheDocument();
  });

  it.each([
    /last 7 days/i,
    /last 30 days/i,
    /this month/i,
  ])("applies the %s preset and closes the popover", async (preset) => {
    renderFilter();
    await openPopover();
    await click(screen.getByText(preset));
    expect(screen.queryByText(preset)).not.toBeInTheDocument();
    expect(screen.queryByText("Date range")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /clear date range/i }),
    ).toBeInTheDocument();
  });

  it("clears the range from the external clear button", async () => {
    renderFilter();
    await openPopover();
    await click(screen.getByText(/last 7 days/i));
    await click(screen.getByRole("button", { name: /clear date range/i }));
    expect(
      screen.queryByRole("button", { name: /clear date range/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Date range")).toBeInTheDocument();
  });

  it("clears the range from the Clear button inside the popover", async () => {
    renderFilter();
    await openPopover();
    await click(screen.getByText(/last 7 days/i));
    const trigger = screen
      .getAllByRole("button")
      .find((b) => b.getAttribute("aria-haspopup") === "dialog");
    if (!trigger) throw new Error("trigger not found");
    await click(trigger);
    await click(screen.getByRole("button", { name: /^clear$/i }));
    expect(screen.getByText("Date range")).toBeInTheDocument();
  });

  it("selects a range by clicking two calendar days", async () => {
    renderFilter();
    await openPopover();
    const enabledDays = screen
      .getAllByRole("gridcell")
      .filter(
        (cell) =>
          cell.tagName === "BUTTON" &&
          !cell.hasAttribute("disabled") &&
          !cell.className.includes("day-outside"),
      );
    await click(enabledDays[0]);
    await click(enabledDays[1]);
    expect(screen.queryByText("Date range")).not.toBeInTheDocument();
  });
});
