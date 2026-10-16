import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Calendar } from "./calendar";

describe("Calendar", () => {
  it("renders the calendar grid", () => {
    render(<Calendar mode="single" />);
    expect(screen.getByRole("grid")).toBeInTheDocument();
  });

  it("renders navigation buttons with chevron icons", () => {
    render(<Calendar mode="single" />);
    // DayPicker renders two nav buttons (previous/next month) that use our custom icons
    const navButtons = screen.getAllByRole("button");
    expect(navButtons.length).toBeGreaterThanOrEqual(2);
  });

  it("applies extra className to the root element", () => {
    const { container } = render(
      <Calendar mode="single" className="my-custom" />,
    );
    expect(container.firstChild).toHaveClass("my-custom");
  });

  it("renders day numbers for the current month", () => {
    render(<Calendar mode="single" />);
    // At least one day button should be visible
    const dayButtons = screen.getAllByRole("gridcell");
    expect(dayButtons.length).toBeGreaterThan(0);
  });
});
