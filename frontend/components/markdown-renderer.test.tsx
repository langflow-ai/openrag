import { describe, expect, it } from "vitest";
import { renderWithProviders, screen } from "@/test-utils/render";
import { MarkdownRenderer } from "./markdown-renderer";

describe("MarkdownRenderer", () => {
  it("renders mathematical notation as readable text", () => {
    renderWithProviders(
      <MarkdownRenderer chatMessage={"Euler: $e^{i\\pi} + 1 = 0$"} />,
    );

    expect(screen.getByText("Euler:")).toBeVisible();
    expect(screen.getByText("e^{i\\pi} + 1 = 0").textContent).toBe(
      "e^{i\\pi} + 1 = 0",
    );
  });
});
