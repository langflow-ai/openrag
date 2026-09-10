import { describe, expect, it } from "vitest";
import type { File as SearchFile } from "@/app/api/queries/useGetSearchQuery";
import type { TaskFile } from "@/contexts/task-context";
import {
  buildActiveSourceOptions,
  buildKnowledgeTableRows,
  getKnowledgeFileAliasKeys,
  getKnowledgeFileIdentity,
  inferTaskFileConnectorType,
  resolveKnowledgeRowConnectorType,
} from "./knowledge-table-state";

/**
 * Chosen by churn: 5 of this file's 7 commits in the last year were bug fixes.
 * The `regressions` block below pins one behaviour per shipped fix, named with
 * its PR, so a future refactor cannot quietly reintroduce them.
 */

function searchFile(overrides: Partial<SearchFile> = {}): SearchFile {
  return {
    filename: "doc.pdf",
    mimetype: "application/pdf",
    source_url: "",
    size: 100,
    connector_type: "local",
    ...overrides,
  };
}

function taskFile(overrides: Partial<TaskFile> = {}): TaskFile {
  return {
    filename: "doc.pdf",
    mimetype: "application/pdf",
    source_url: "",
    size: 100,
    connector_type: "local",
    status: "processing",
    task_id: "t1",
    created_at: "2026-09-08T10:00:00Z",
    updated_at: "2026-09-08T10:00:00Z",
    ...overrides,
  };
}

describe("getKnowledgeFileIdentity", () => {
  it("prefers filename, falls back to source_url, else empty", () => {
    expect(getKnowledgeFileIdentity({ filename: "a.pdf" })).toBe("a.pdf");
    expect(
      getKnowledgeFileIdentity({ filename: "  ", source_url: "http://x/a" }),
    ).toBe("http://x/a");
    expect(getKnowledgeFileIdentity({})).toBe("");
    expect(getKnowledgeFileIdentity()).toBe("");
  });
});

describe("getKnowledgeFileAliasKeys", () => {
  it("pairs .txt and .md so either spelling matches", () => {
    expect(getKnowledgeFileAliasKeys({ filename: "notes.txt" })).toContain(
      "notes.md",
    );
    expect(getKnowledgeFileAliasKeys({ filename: "notes.md" })).toContain(
      "notes.txt",
    );
  });

  it("adds underscore variants for spaces and slashes", () => {
    const keys = getKnowledgeFileAliasKeys({ filename: "my report/v2.txt" });
    expect(keys).toContain("my report/v2.txt");
    expect(keys).toContain("my_report_v2.txt");
    // Extension pairing applies to the underscored variant too.
    expect(keys).toContain("my_report_v2.md");
  });

  it("does not derive variants from an http url filename", () => {
    expect(
      getKnowledgeFileAliasKeys({ filename: "https://x.dev/a.txt" }),
    ).toEqual(["https://x.dev/a.txt"]);
  });

  it("indexes a source_url by both full url and basename", () => {
    const keys = getKnowledgeFileAliasKeys({
      filename: "",
      source_url: "s3://bucket/deep/report.txt",
    });
    expect(keys).toContain("s3://bucket/deep/report.txt");
    expect(keys).toContain("report.txt");
    expect(keys).toContain("report.md");
  });

  it("returns no keys for an empty file", () => {
    expect(getKnowledgeFileAliasKeys({})).toEqual([]);
    expect(getKnowledgeFileAliasKeys()).toEqual([]);
  });
});

describe("inferTaskFileConnectorType", () => {
  it("trusts a meaningful connector type from the task", () => {
    expect(inferTaskFileConnectorType("a.pdf", "a.pdf", "  aws_s3 ")).toBe(
      "aws_s3",
    );
  });

  it("ignores 'local' and blank as non-meaningful", () => {
    expect(inferTaskFileConnectorType("a.pdf", "a.pdf", "local")).toBe("local");
    expect(inferTaskFileConnectorType("a.pdf", "a.pdf", "   ")).toBe("local");
  });

  it("classifies http paths as url, and openr.ag as openrag_docs", () => {
    expect(inferTaskFileConnectorType("https://example.com/a", "a")).toBe(
      "url",
    );
    expect(inferTaskFileConnectorType("https://openr.ag/docs/x", "x")).toBe(
      "openrag_docs",
    );
  });

  it("falls back to the filename when the path is not a url", () => {
    expect(inferTaskFileConnectorType("", "https://example.com/a")).toBe("url");
  });

  it("defaults to local for bucket-style keys it cannot distinguish", () => {
    expect(inferTaskFileConnectorType("container::blob", "blob")).toBe("local");
  });
});

describe("resolveKnowledgeRowConnectorType", () => {
  it("prefers the backend type for active rows", () => {
    expect(resolveKnowledgeRowConnectorType("aws_s3", "url", "active")).toBe(
      "aws_s3",
    );
  });

  it("prefers the task type for non-active rows", () => {
    expect(
      resolveKnowledgeRowConnectorType("aws_s3", "url", "processing"),
    ).toBe("url");
  });

  it("skips a non-meaningful backend type in favour of the task type", () => {
    expect(
      resolveKnowledgeRowConnectorType("local", "azure_blob", "active"),
    ).toBe("azure_blob");
  });

  it("falls back to local when neither side offers anything", () => {
    expect(resolveKnowledgeRowConnectorType(undefined, undefined)).toBe(
      "local",
    );
  });

  it("treats a missing status as active", () => {
    expect(resolveKnowledgeRowConnectorType("aws_s3", "url")).toBe("aws_s3");
  });
});

describe("buildKnowledgeTableRows", () => {
  it("returns backend rows untouched when there are no task overlays", () => {
    const rows = buildKnowledgeTableRows([searchFile()], []);
    expect(rows).toHaveLength(1);
    expect(rows[0].filename).toBe("doc.pdf");
  });

  it("appends task files that the index does not yet know about", () => {
    const rows = buildKnowledgeTableRows(
      [searchFile({ filename: "indexed.pdf" })],
      [taskFile({ filename: "brand-new.pdf" })],
    );
    expect(rows.map((r) => r.filename)).toEqual([
      "indexed.pdf",
      "brand-new.pdf",
    ]);
  });

  it("labels a task file with no name or url as Untitled source", () => {
    const rows = buildKnowledgeTableRows(
      [],
      [taskFile({ filename: "", source_url: "" })],
    );
    expect(rows[0].filename).toBe("Untitled source");
  });

  it("leaves openrag_docs backend rows entirely alone", () => {
    const rows = buildKnowledgeTableRows(
      [searchFile({ connector_type: "openrag_docs", status: "active" })],
      [taskFile({ status: "failed", error: "boom" })],
    );
    expect(rows[0].status).toBe("active");
    expect(rows[0].error).toBeUndefined();
  });

  describe("regressions", () => {
    it("does not duplicate a file that the index already lists (#1892)", () => {
      // The overlay and the indexed row are the same document; only one row.
      const rows = buildKnowledgeTableRows(
        [searchFile({ filename: "report.pdf" })],
        [taskFile({ filename: "report.pdf" })],
      );
      expect(rows).toHaveLength(1);
    });

    it("dedupes across .txt/.md and underscore aliases (#1892)", () => {
      const rows = buildKnowledgeTableRows(
        [searchFile({ filename: "my notes.txt" })],
        [taskFile({ filename: "my_notes.md" })],
      );
      expect(rows).toHaveLength(1);
    });

    it("keeps the connector icon source for url rows (#1887)", () => {
      const rows = buildKnowledgeTableRows(
        [searchFile({ filename: "page", connector_type: "" })],
        [taskFile({ filename: "page", connector_type: "url" })],
      );
      expect(rows[0].connector_type).toBe("url");
    });

    it("keeps a meaningful backend connector type over the overlay (#1887)", () => {
      const rows = buildKnowledgeTableRows(
        [searchFile({ filename: "obj", connector_type: "azure_blob" })],
        [taskFile({ filename: "obj", connector_type: "url" })],
      );
      expect(rows[0].connector_type).toBe("azure_blob");
    });

    it("merges embedding metadata from the overlay onto the row (#1576)", () => {
      const rows = buildKnowledgeTableRows(
        [searchFile({ filename: "a.pdf" })],
        [
          taskFile({
            filename: "a.pdf",
            embedding_model: "granite-embed",
            embedding_dimensions: 768,
          }),
        ],
      );
      expect(rows[0].embedding_model).toBe("granite-embed");
      expect(rows[0].embedding_dimensions).toBe(768);
    });

    it("does not let an overlay erase embedding metadata it lacks (#1576)", () => {
      const rows = buildKnowledgeTableRows(
        [
          searchFile({
            filename: "a.pdf",
            embedding_model: "backend-model",
            embedding_dimensions: 1024,
          }),
        ],
        [taskFile({ filename: "a.pdf" })],
      );
      expect(rows[0].embedding_model).toBe("backend-model");
      expect(rows[0].embedding_dimensions).toBe(1024);
    });

    it("hides unindexed processing rows while a filter is active (#1282)", () => {
      const rows = buildKnowledgeTableRows(
        [searchFile({ filename: "indexed.pdf" })],
        [taskFile({ filename: "still-processing.pdf" })],
        true,
      );
      expect(rows.map((r) => r.filename)).toEqual(["indexed.pdf"]);
    });

    it("still overlays status onto matched rows when filtered (#1282)", () => {
      const rows = buildKnowledgeTableRows(
        [searchFile({ filename: "a.pdf", status: "active" })],
        [taskFile({ filename: "a.pdf", status: "processing" })],
        true,
      );
      expect(rows).toHaveLength(1);
      expect(rows[0].status).toBe("processing");
    });

    it("excludes the OpenRAG docs refresh pseudo-task (#1282)", () => {
      const rows = buildKnowledgeTableRows(
        [],
        [
          taskFile({ filename: "OpenRAG docs refresh" }),
          taskFile({ filename: "d", source_url: "https://openr.ag/docs" }),
          taskFile({ filename: "e", connector_type: "openrag_docs" }),
        ],
      );
      expect(rows).toEqual([]);
    });

    it("promotes processing and failed status onto the indexed row", () => {
      const processing = buildKnowledgeTableRows(
        [searchFile({ filename: "a.pdf", status: "active" })],
        [taskFile({ filename: "a.pdf", status: "processing" })],
      );
      expect(processing[0].status).toBe("processing");

      const failed = buildKnowledgeTableRows(
        [searchFile({ filename: "a.pdf", status: "active" })],
        [taskFile({ filename: "a.pdf", status: "failed", error: "nope" })],
      );
      expect(failed[0].status).toBe("failed");
      expect(failed[0].error).toBe("nope");
    });

    it("keeps the backend status when the overlay is merely active", () => {
      const rows = buildKnowledgeTableRows(
        [searchFile({ filename: "a.pdf", status: "unavailable" })],
        [taskFile({ filename: "a.pdf", status: "active" })],
      );
      expect(rows[0].status).toBe("unavailable");
    });

    it("prefers the highest-priority overlay when several share a key", () => {
      const rows = buildKnowledgeTableRows(
        [searchFile({ filename: "a.pdf", status: "active" })],
        [
          taskFile({ filename: "a.pdf", status: "active" }),
          taskFile({ filename: "a.pdf", status: "processing" }),
        ],
      );
      expect(rows[0].status).toBe("processing");
    });
  });
});

describe("buildActiveSourceOptions", () => {
  // acc4d1c2b — "align source filter options with active table rows".
  it("lists only active rows, deduped and sorted (acc4d1c2b)", () => {
    const options = buildActiveSourceOptions([
      searchFile({ filename: "zebra.pdf", status: "active" }),
      searchFile({ filename: "apple.pdf", status: "active" }),
      searchFile({ filename: "apple.pdf", status: "active" }),
      searchFile({ filename: "hidden.pdf", status: "processing" }),
      searchFile({ filename: "gone.pdf", status: "failed" }),
    ]);

    expect(options.map((o) => o.value)).toEqual(["apple.pdf", "zebra.pdf"]);
  });

  it("treats a missing status as active", () => {
    const options = buildActiveSourceOptions([
      searchFile({ filename: "a.pdf", status: undefined }),
    ]);
    expect(options).toHaveLength(1);
  });

  it("falls back to source_url when there is no filename", () => {
    const options = buildActiveSourceOptions([
      searchFile({
        filename: "",
        source_url: "https://x.dev/a",
        status: "active",
      }),
    ]);
    expect(options[0].value).toBe("https://x.dev/a");
  });

  it("skips rows with neither filename nor source_url", () => {
    expect(
      buildActiveSourceOptions([searchFile({ filename: "", source_url: "" })]),
    ).toEqual([]);
  });
});
