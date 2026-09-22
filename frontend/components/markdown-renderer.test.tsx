import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkdownRenderer } from "./markdown-renderer";

describe("MarkdownRenderer", () => {
  it("renders mathematical notation without a Node require runtime", () => {
    const { container } = render(
      <MarkdownRenderer chatMessage={"Euler: $e^{i\\pi} + 1 = 0$"} />,
    );

    expect(container.querySelector("math annotation")).toHaveTextContent(
      "e^{i\\pi} + 1 = 0",
    );
  });
});
