import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge } from "./status-badge";

/**
 * This badge reads its label and colour out of a lookup keyed by status, and
 * callers take that status straight off an API response. When a file arrived
 * as "skipped" — which has no entry — the unguarded `statusConfig[status]
 * .className` threw, React's error boundary caught it, and the whole knowledge
 * view was replaced by "Component rendering error" (tracker #92808).
 *
 * A presentational badge must not be able to take a page down, whatever the
 * backend sends.
 */

describe("StatusBadge", () => {
  it("renders the mapped label for a known status", () => {
    render(<StatusBadge status="active" />);
    expect(screen.getByText("Active")).toBeTruthy();
  });

  it("renders a skipped file rather than throwing", () => {
    render(<StatusBadge status="skipped" />);
    expect(screen.getByText("Skipped")).toBeTruthy();
  });

  it("renders an unmapped status as its own name", () => {
    render(<StatusBadge status="queued" />);
    expect(screen.getByText("Queued")).toBeTruthy();
  });

  it("humanises a multi-word unmapped status", () => {
    render(<StatusBadge status="in_progress" />);
    expect(screen.getByText("In progress")).toBeTruthy();
  });

  it("falls back to a label when the status is empty", () => {
    render(<StatusBadge status="" />);
    expect(screen.getByText("Unknown")).toBeTruthy();
  });

  it("keeps the caller's className alongside the status colour", () => {
    const { container } = render(
      <StatusBadge status="failed" className="pointer-events-none" />,
    );
    const el = container.firstElementChild as HTMLElement;
    expect(el.className).toContain("pointer-events-none");
    expect(el.className).toContain("text-accent-red-foreground");
  });
});
