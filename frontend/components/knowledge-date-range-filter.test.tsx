import { act, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
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
    expect(
      screen.getByRole("button", { name: /last 7 days/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /last 30 days/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /this month/i }),
    ).toBeInTheDocument();
  });

  it.each([
    /last 7 days/i,
    /last 30 days/i,
    /this month/i,
  ])("applies the %s preset and closes the popover", async (preset) => {
    renderFilter();
    await openPopover();
    await click(screen.getByRole("button", { name: preset }));
    expect(
      screen.queryByRole("button", { name: preset }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Date range")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /clear date range/i }),
    ).toBeInTheDocument();
  });

  it("clears the range from the external clear button", async () => {
    renderFilter();
    await openPopover();
    await click(screen.getByRole("button", { name: /last 7 days/i }));
    await click(screen.getByRole("button", { name: /clear date range/i }));
    expect(
      screen.queryByRole("button", { name: /clear date range/i }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Date range")).toBeInTheDocument();
  });

  it("clears the range from the Clear button inside the popover", async () => {
    renderFilter();
    await openPopover();
    await click(screen.getByRole("button", { name: /last 7 days/i }));
    const trigger = screen
      .getAllByRole("button")
      .find((b) => b.getAttribute("aria-haspopup") === "dialog");
    if (!trigger) throw new Error("trigger not found");
    await click(trigger);
    await click(screen.getByRole("button", { name: /^clear$/i }));
    expect(screen.getByText("Date range")).toBeInTheDocument();
  });

  describe("calendar range selection", () => {
    // Only Date is faked so act()/Radix timers keep running normally.
    beforeEach(() => {
      vi.useFakeTimers({ toFake: ["Date"] });
      vi.setSystemTime(new Date(2024, 5, 20, 12));
    });
    afterEach(() => {
      vi.useRealTimers();
    });

    it("selects a range by clicking two calendar days", async () => {
      renderFilter();
      await openPopover();
      // June 2024 is the first month shown; July is fully disabled (after today).
      const juneDay = (day: number) => {
        const cell = screen
          .getAllByRole("gridcell")
          .find(
            (c) =>
              c.tagName === "BUTTON" &&
              !c.hasAttribute("disabled") &&
              !c.className.includes("day-outside") &&
              c.textContent === String(day),
          );
        if (!cell) throw new Error(`June ${day} not selectable`);
        return cell;
      };
      await click(juneDay(10));
      await click(juneDay(15));

      const fmt = (d: Date) =>
        d.toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
          year: "numeric",
        });
      const expected = `${fmt(new Date(2024, 5, 10))} – ${fmt(new Date(2024, 5, 15))}`;
      expect(screen.queryByText("Date range")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: expected })).toHaveTextContent(
        expected,
      );
      expect(
        screen.queryByRole("button", { name: /last 7 days/i }),
      ).not.toBeInTheDocument();
    });
  });
});
