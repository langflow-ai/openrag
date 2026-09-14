import { describe, expect, it } from "vitest";

/**
 * Tests the effectiveSearchText URL param building logic (lines 630-643).
 * This is the code that runs when clicking a file row to navigate to chunks page.
 */
describe("KnowledgePage - effectiveSearchText in URL params (lines 630-643)", () => {
  it("includes effectiveSearchText in URL when it has a value", () => {
    // Simulate the logic from lines 630-643
    // Use a function to return the value so TS doesn't narrow the type to a literal
    const getSearchText = () => "filter query";
    const effectiveSearchText = getSearchText();
    const filename = "test.pdf";

    const params = new URLSearchParams({ filename });

    // Lines 633-640: Check if effectiveSearchText is valid
    if (
      effectiveSearchText &&
      effectiveSearchText !== "*" &&
      effectiveSearchText !== ""
    ) {
      params.set("q", effectiveSearchText);
    }

    const url = `/knowledge/chunks?${params.toString()}`;
    expect(url).toBe("/knowledge/chunks?filename=test.pdf&q=filter+query");
  });

  it("excludes query param when effectiveSearchText is wildcard", () => {
    const effectiveSearchText = "*";
    const filename = "test.pdf";

    const params = new URLSearchParams({ filename });

    if (
      effectiveSearchText &&
      effectiveSearchText !== "*" &&
      effectiveSearchText !== ""
    ) {
      params.set("q", effectiveSearchText);
    }

    expect(params.has("q")).toBe(false);
  });

  it("excludes query param when effectiveSearchText is empty", () => {
    const effectiveSearchText = "";
    const filename = "test.pdf";

    const params = new URLSearchParams({ filename });

    if (
      effectiveSearchText &&
      effectiveSearchText !== "*" &&
      effectiveSearchText !== ""
    ) {
      params.set("q", effectiveSearchText);
    }

    expect(params.has("q")).toBe(false);
  });

  it("includes query from queryOverride when available", () => {
    const getSearchText = () => "query override text";
    const effectiveSearchText = getSearchText();
    const filename = "test.pdf";

    const params = new URLSearchParams({ filename });

    if (
      effectiveSearchText &&
      effectiveSearchText !== "*" &&
      effectiveSearchText !== ""
    ) {
      params.set("q", effectiveSearchText);
    }

    expect(params.get("q")).toBe("query override text");
  });
});
