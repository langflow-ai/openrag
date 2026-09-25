import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HighlightedText } from "./highlighted-text";

describe("HighlightedText", () => {
  it("renders fallback text when highlights array is empty", () => {
    render(
      <HighlightedText
        highlights={[]}
        fallbackText="No highlights available"
      />,
    );
    expect(screen.getByText("No highlights available")).toBeInTheDocument();
  });

  it("renders fallback text when highlights is undefined", () => {
    render(
      <HighlightedText
        highlights={undefined as any}
        fallbackText="No highlights"
      />,
    );
    expect(screen.getByText("No highlights")).toBeInTheDocument();
  });

  it("renders a single highlight fragment with mark tags", () => {
    const { container } = render(
      <HighlightedText
        highlights={["foo <mark>bar</mark> baz"]}
        fallbackText="No highlights"
      />,
    );
    const mark = container.querySelector("mark");
    expect(mark).toBeInTheDocument();
    expect(mark?.textContent).toBe("bar");
    expect(container.textContent).toContain("foo");
    expect(container.textContent).toContain("baz");
  });

  it("renders multiple highlight fragments with ellipsis separators", () => {
    const { container } = render(
      <HighlightedText
        highlights={["first <mark>match</mark>", "second <mark>hit</mark>"]}
        fallbackText="No highlights"
      />,
    );
    const marks = container.querySelectorAll("mark");
    expect(marks).toHaveLength(2);
    expect(marks[0].textContent).toBe("match");
    expect(marks[1].textContent).toBe("hit");
    expect(container.textContent).toContain("…");
  });

  it("handles fragments without mark tags", () => {
    render(
      <HighlightedText
        highlights={["plain text without marks"]}
        fallbackText="No highlights"
      />,
    );
    expect(screen.getByText("plain text without marks")).toBeInTheDocument();
  });

  it("handles multiple mark tags in a single fragment", () => {
    const { container } = render(
      <HighlightedText
        highlights={["foo <mark>bar</mark> middle <mark>baz</mark> end"]}
        fallbackText="No highlights"
      />,
    );
    const marks = container.querySelectorAll("mark");
    expect(marks).toHaveLength(2);
    expect(marks[0].textContent).toBe("bar");
    expect(marks[1].textContent).toBe("baz");
  });

  it("applies custom className to the root span", () => {
    const { container } = render(
      <HighlightedText
        highlights={["test <mark>text</mark>"]}
        fallbackText="fallback"
        className="custom-class"
      />,
    );
    const rootSpan = container.querySelector("span.custom-class");
    expect(rootSpan).toBeInTheDocument();
  });

  it("applies highlight styling classes to mark elements", () => {
    const { container } = render(
      <HighlightedText
        highlights={["<mark>highlighted</mark>"]}
        fallbackText="fallback"
      />,
    );
    const mark = container.querySelector("mark");
    expect(mark?.className).toContain("bg-yellow-200");
    expect(mark?.className).toContain("dark:bg-yellow-800");
    expect(mark?.className).toContain("text-foreground");
  });

  it("uses stable keys based on fragment content and position", () => {
    const { container } = render(
      <HighlightedText
        highlights={["first", "second", "first"]}
        fallbackText="fallback"
      />,
    );
    // Check that all fragments are rendered
    const spans = container.querySelectorAll("span > span");
    expect(spans.length).toBeGreaterThanOrEqual(3);
  });

  it("handles empty string fragments gracefully", () => {
    const { container } = render(
      <HighlightedText
        highlights={["text <mark></mark> more"]}
        fallbackText="fallback"
      />,
    );
    const mark = container.querySelector("mark");
    expect(mark).toBeInTheDocument();
    expect(mark?.textContent).toBe("");
  });
});
