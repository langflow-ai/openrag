import { describe, expect, it } from "vitest";
import { buildChunksUrl } from "./chunks-url";

describe("buildChunksUrl", () => {
  it("adds the query when there is one", () => {
    expect(buildChunksUrl("report.pdf", "quarterly revenue")).toBe(
      "/knowledge/chunks?filename=report.pdf&q=quarterly+revenue",
    );
  });

  it("trims the query before adding it", () => {
    expect(buildChunksUrl("report.pdf", "  docling  ")).toBe(
      "/knowledge/chunks?filename=report.pdf&q=docling",
    );
  });

  it.each(["", "   ", "*", " * "])("omits q for %j", (query) => {
    expect(buildChunksUrl("report.pdf", query)).toBe(
      "/knowledge/chunks?filename=report.pdf",
    );
  });

  it("encodes characters that would break the URL", () => {
    const url = buildChunksUrl("my doc & notes.pdf", "cost/benefit");
    const params = new URL(url, "http://localhost").searchParams;
    expect(params.get("filename")).toBe("my doc & notes.pdf");
    expect(params.get("q")).toBe("cost/benefit");
  });
});
