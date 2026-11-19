import { describe, expect, it } from "vitest";
import type { ToolCallResult } from "@/app/chat/_types/types";
import {
  deriveDisplayFilename,
  preprocessCitations,
} from "./markdown-citations";

const dataset = (name: string) => ({
  id: `id-${name}`,
  name,
  import_name: "Lab import",
  source_index: "idx",
});

// Two datasets whose results share the same title, plus a document result.
const sources: ToolCallResult[] = [
  {
    chunk_id: "ds-1-UGhvdG8",
    id: "ds-1-UGhvdG8",
    filename: "Scientists / Photo 51",
    dataset: dataset("Scientists"),
    text: "from scientists",
  },
  {
    chunk_id: "ds-2-UGhvdG8",
    id: "ds-2-UGhvdG8",
    filename: "Scientists / Photo 51",
    dataset: dataset("Discoveries"),
    text: "from discoveries",
  },
  { chunk_id: "doc-1", filename: "Photo 51", dataset: null, text: "document" },
];

describe("preprocessCitations with dataset sources", () => {
  it("resolves each citation by chunk_id even when titles are duplicated", () => {
    const { text, citedSources } = preprocessCitations(
      "A (Source: ds-2-UGhvdG8) B [Source: ds-1-UGhvdG8, doc-1]",
      sources,
    );
    expect(citedSources.map((c) => c.item.chunk_id)).toEqual([
      "ds-2-UGhvdG8",
      "ds-1-UGhvdG8",
      "doc-1",
    ]);
    expect(citedSources.map((c) => c.index)).toEqual([1, 2, 3]);
    expect(text).toBe(
      "A [\\[1\\]](#citation-1) B [\\[2\\]](#citation-2)[\\[3\\]](#citation-3)",
    );
  });

  it("does not guess between sources when only the shared title is cited", () => {
    const { citedSources } = preprocessCitations(
      "(Source: Scientists / Photo 51)",
      sources,
    );
    expect(citedSources).toEqual([]);
  });

  it("reuses one number for repeated citations of the same chunk", () => {
    const { citedSources } = preprocessCitations(
      "(Source: ds-1-UGhvdG8) and (Source: ds-1-UGhvdG8)",
      sources,
    );
    expect(citedSources).toHaveLength(1);
  });
});

describe("deriveDisplayFilename", () => {
  it("keeps the last path segment for documents", () => {
    expect(deriveDisplayFilename("/docs/a/report.pdf", undefined)).toBe(
      "report.pdf",
    );
  });

  it("strips the dataset prefix instead of splitting on slashes", () => {
    expect(
      deriveDisplayFilename(
        undefined,
        "Scientists / AC/DC history",
        "Document",
        { name: "Scientists" },
      ),
    ).toBe("AC/DC history");
  });

  it("falls back when a dataset result has no title", () => {
    expect(
      deriveDisplayFilename(undefined, "", "document", { name: "Scientists" }),
    ).toBe("document");
  });
});
