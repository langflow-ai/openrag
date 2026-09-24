import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { UrlSourceDialog } from "./url-source-dialog";

describe("UrlSourceDialog", () => {
  it("switches between source and re-sync steps from the dialog header", async () => {
    const user = userEvent.setup();

    render(<UrlSourceDialog open onOpenChange={vi.fn()} />);

    const sourceTab = screen.getByRole("button", { name: "Source & scope" });
    const resyncTab = screen.getByRole("button", { name: "Re-sync behavior" });

    expect(sourceTab).toHaveAttribute("aria-current", "step");
    expect(
      screen.getByRole("heading", { name: "Where should we crawl?" }),
    ).toBeInTheDocument();

    await user.click(resyncTab);

    expect(resyncTab).toHaveAttribute("aria-current", "step");
    expect(
      screen.getByRole("heading", { name: "How should re-syncs work?" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Back" }),
    ).not.toBeInTheDocument();

    await user.click(sourceTab);

    expect(sourceTab).toHaveAttribute("aria-current", "step");
    expect(
      screen.getByRole("heading", { name: "Where should we crawl?" }),
    ).toBeInTheDocument();
  });
});
