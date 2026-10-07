import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { type Status, StatusBadge } from "./status-badge";

describe("StatusBadge", () => {
  it("renders the label for a known status", () => {
    render(<StatusBadge status="skipped" />);
    expect(screen.getByText("Skipped")).toBeInTheDocument();
  });

  it("falls back to the raw status instead of crashing on an unknown one", () => {
    render(<StatusBadge status={"queued" as Status} />);
    expect(screen.getByText("queued")).toBeInTheDocument();
  });
});
