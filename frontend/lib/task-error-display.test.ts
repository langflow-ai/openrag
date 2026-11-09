import { describe, expect, it } from "vitest";
import type {
  TaskFailurePhase,
  TaskFileEntry,
} from "@/app/api/queries/useGetTasksQuery";
import {
  analyzeTaskFileIngestionFailure,
  buildRowStatusLabel,
  FILE_ERROR_MAX_LINE_LENGTH,
  formatApiComponent,
  getTaskFailureToastDescription,
  normalizeFailurePhase,
  resolveTaskFileError,
} from "./task-error-display";

/**
 * Chosen by churn: 3 of this file's 9 commits in the last year were bug fixes
 * (#2152 "provide real error for onboarding apiKey setup and settings", #2127
 * "surface provider errors in chat instead of generic connection failures",
 * #1771 "cancel case not retryable"), plus #1769 which added skipped-task
 * warnings.
 *
 * `formatProviderErrorMessage` is deliberately NOT stubbed — the #2127 fix is
 * precisely that these messages get run through it, so the real function is
 * part of what is under test.
 */

function entry(overrides: Partial<TaskFileEntry> = {}): TaskFileEntry {
  return { status: "failed", ...overrides };
}

// A real _update_by_query 409 as opensearch-py renders it: the whole response
// body becomes the exception message, because that response carries no
// top-level "error" key for the client to use instead (#2349).
const OPENSEARCH_CONFLICT_ERROR =
  'ConflictError(409, \'{"took":2719,"timed_out":false,"total":300,' +
  '"updated":19,"version_conflicts":1,"failures":[{"index":"documents",' +
  '"id":"20","cause":{"type":"version_conflict_engine_exception"}}]}\')';

const BACKEND_CLASSIFIED_MESSAGE =
  "The search index was busy and this change conflicted with another " +
  "update. Nothing is wrong with the file — retry ingestion.";

describe("formatApiComponent", () => {
  it("maps every known component to its display label", () => {
    expect(formatApiComponent("docling")).toBe("Docling");
    expect(formatApiComponent("openrag")).toBe("OpenRAG");
    expect(formatApiComponent("langflow")).toBe("Langflow");
    expect(formatApiComponent("opensearch")).toBe("OpenSearch");
  });

  it("returns undefined when no component is given", () => {
    expect(formatApiComponent(undefined)).toBeUndefined();
  });
});

describe("normalizeFailurePhase", () => {
  it("accepts every known phase", () => {
    for (const phase of [
      "parsing",
      "chunking",
      "embedding",
      "indexing",
      "file_validation",
      "cancelled",
      "unknown",
    ]) {
      expect(normalizeFailurePhase(phase)).toBe(phase);
    }
  });

  it("rejects unknown or missing phases", () => {
    expect(normalizeFailurePhase("teleporting")).toBeUndefined();
    expect(normalizeFailurePhase("")).toBeUndefined();
    expect(normalizeFailurePhase(undefined)).toBeUndefined();
  });
});

describe("buildRowStatusLabel", () => {
  it("uses bespoke wording for cancelled, validation and unknown (#1771)", () => {
    expect(buildRowStatusLabel("cancelled")).toBe("Cancelled");
    expect(buildRowStatusLabel("file_validation")).toBe(
      "File validation issue",
    );
    expect(buildRowStatusLabel("unknown")).toBe("Failed");
  });

  it("suffixes pipeline phases with 'issue'", () => {
    expect(buildRowStatusLabel("parsing")).toBe("Parsing issue");
    expect(buildRowStatusLabel("embedding")).toBe("Embedding issue");
  });
});

describe("resolveTaskFileError", () => {
  it("prefers a result warning over everything else (#1769)", () => {
    const message = resolveTaskFileError(
      entry({
        result: { warning: "Skipped: unsupported page" },
        user_facing_message: "ignored",
        error: "ignored too",
      }),
      "task level ignored",
    );

    expect(message).toContain("unsupported page");
  });

  it("falls back to user_facing_message, then error, then task error (#2152)", () => {
    expect(
      resolveTaskFileError(
        entry({ user_facing_message: "Invalid API key", error: "raw" }),
        "task",
      ),
    ).toBe("Invalid API key");

    expect(resolveTaskFileError(entry({ error: "raw failure" }), "task")).toBe(
      "raw failure",
    );

    expect(resolveTaskFileError(entry({}), "task level boom")).toBe(
      "task level boom",
    );
  });

  it("skips blank candidates rather than returning empty text", () => {
    expect(
      resolveTaskFileError(
        entry({
          result: { warning: "   " },
          user_facing_message: "  ",
          error: "  ",
        }),
        "  ",
      ),
    ).toBe("Unknown error");
  });

  it("ignores a result object without a string warning", () => {
    expect(
      resolveTaskFileError(entry({ result: { warning: 42 }, error: "real" })),
    ).toBe("real");
  });

  it("returns Unknown error when nothing is available", () => {
    expect(resolveTaskFileError(entry({}))).toBe("Unknown error");
  });

  it("runs messages through provider-error formatting (#2127)", () => {
    // A raw provider JSON blob must not reach the UI verbatim.
    const message = resolveTaskFileError(
      entry({ error: '{"message": "Rate limit exceeded"}' }),
    );

    expect(message).not.toContain("{");
    expect(message).toContain("Rate limit exceeded");
  });

  it("prefers the backend's classified message over a raw payload (#2349)", () => {
    // This precedence is what makes the backend classifier work at all. If these
    // checks are ever reordered, a classified OpenSearch failure would fall back
    // to the raw payload and be mangled again.
    expect(
      resolveTaskFileError(
        entry({
          error: OPENSEARCH_CONFLICT_ERROR,
          user_facing_message: BACKEND_CLASSIFIED_MESSAGE,
        }),
      ),
    ).toBe(BACKEND_CLASSIFIED_MESSAGE);
  });

  it("passes a clean sentence through the provider parser unchanged (#2349)", () => {
    // The message contains no JSON, so the chat provider-error parser must not
    // rewrite or truncate it.
    expect(
      resolveTaskFileError(
        entry({ user_facing_message: BACKEND_CLASSIFIED_MESSAGE }),
      ),
    ).toBe(BACKEND_CLASSIFIED_MESSAGE);
  });

  it("keeps the whole raw error when the backend did not classify it (#2349)", () => {
    // Regression guard: this used to collapse to the 20-character fragment
    // "ConflictError(409, '", discarding the failures[] array that names the
    // index, shard and document — the only way to diagnose the failure.
    const resolved = resolveTaskFileError(
      entry({ error: OPENSEARCH_CONFLICT_ERROR }),
    );

    expect(resolved).toBe(OPENSEARCH_CONFLICT_ERROR);
    expect(resolved).toContain("version_conflict_engine_exception");
  });
});

describe("getTaskFailureToastDescription", () => {
  it("uses the first meaningful failed-file message", () => {
    const description = getTaskFailureToastDescription({
      files: {
        "ok.pdf": entry({ status: "completed" }),
        "bad.pdf": entry({ status: "failed", error: "parser died" }),
      },
    });

    expect(description).toBe("parser died");
  });

  it("treats status 'error' as failed too", () => {
    expect(
      getTaskFailureToastDescription({
        files: { "a.pdf": entry({ status: "error", error: "boom" }) },
      }),
    ).toBe("boom");
  });

  it("skips files whose message resolves to Unknown error", () => {
    const description = getTaskFailureToastDescription({
      files: {
        "a.pdf": entry({ status: "failed" }),
        "b.pdf": entry({ status: "failed", error: "real reason" }),
      },
    });

    expect(description).toBe("real reason");
  });

  it("falls back to the task-level error", () => {
    expect(
      getTaskFailureToastDescription({ error: "  task blew up  ", files: {} }),
    ).toBe("task blew up");
  });

  it("falls back to a failed-file count, pluralized", () => {
    expect(getTaskFailureToastDescription({ failed_files: 1 })).toBe(
      "1 file failed",
    );
    expect(getTaskFailureToastDescription({ failed_files: 3 })).toBe(
      "3 files failed",
    );
  });

  it("derives the count from files when failed_files is absent", () => {
    expect(
      getTaskFailureToastDescription({
        files: {
          "a.pdf": entry({ status: "failed" }),
          "b.pdf": entry({ status: "error" }),
          "c.pdf": entry({ status: "completed" }),
        },
      }),
    ).toBe("2 files failed");
  });

  it("returns Unknown error for a task with nothing to report", () => {
    expect(getTaskFailureToastDescription({})).toBe("Unknown error");
    expect(getTaskFailureToastDescription({ error: null, files: null })).toBe(
      "Unknown error",
    );
  });
});

describe("analyzeTaskFileIngestionFailure", () => {
  it("marks earlier pipeline steps completed and the failing one failed", () => {
    const analysis = analyzeTaskFileIngestionFailure(
      entry({ failure_phase: "embedding", error: "vector store down" }),
    );

    expect(analysis.failedStep).toBe("embedding");
    expect(analysis.pipelineSteps).toEqual([
      { id: "parsing", label: "Parsing", status: "completed" },
      { id: "chunking", label: "Chunking", status: "completed" },
      { id: "embedding", label: "Embedding", status: "failed" },
    ]);
    expect(analysis.rowStatusLabel).toBe("Embedding issue");
    expect(analysis.failureSummary).toBe("Failed at embedding");
  });

  it("shows only the failing step for parsing", () => {
    const analysis = analyzeTaskFileIngestionFailure(
      entry({ failure_phase: "parsing" }),
    );

    expect(analysis.pipelineSteps).toEqual([
      { id: "parsing", label: "Parsing", status: "failed" },
    ]);
  });

  it("collapses cancelled to a single step with no pipeline (#1771)", () => {
    const analysis = analyzeTaskFileIngestionFailure(
      entry({ failure_phase: "cancelled" }),
    );

    expect(analysis.pipelineSteps).toEqual([
      { id: "cancelled", label: "Cancelled", status: "failed" },
    ]);
    expect(analysis.rowStatusLabel).toBe("Cancelled");
    expect(analysis.failureSummary).toBe("Cancelled");
  });

  it("collapses file_validation to a single step", () => {
    const analysis = analyzeTaskFileIngestionFailure(
      entry({ failure_phase: "file_validation" }),
    );

    expect(analysis.pipelineSteps).toEqual([
      { id: "file_validation", label: "File validation", status: "failed" },
    ]);
  });

  it("defaults an unrecognized phase to unknown", () => {
    const analysis = analyzeTaskFileIngestionFailure(
      // Cast deliberately: TaskFailurePhase is a closed union, but the backend
      // can send a phase this frontend build has never heard of. That is the
      // case normalizeFailurePhase exists to absorb, so it must be tested.
      entry({ failure_phase: "teleporting" as TaskFailurePhase }),
    );

    expect(analysis.failedStep).toBe("unknown");
    expect(analysis.pipelineSteps).toEqual([
      { id: "unknown", label: "Ingestion", status: "failed" },
    ]);
    expect(analysis.rowStatusLabel).toBe("Failed");
  });

  it("tags the failing component when the API reports one", () => {
    const analysis = analyzeTaskFileIngestionFailure(
      entry({ failure_phase: "indexing", component: "opensearch" }),
    );

    expect(analysis.componentCause).toBe("OpenSearch");
    expect(analysis.componentTags).toEqual(["OpenSearch"]);
  });

  it("leaves component tags empty when none is reported", () => {
    const analysis = analyzeTaskFileIngestionFailure(entry({}));

    expect(analysis.componentCause).toBeUndefined();
    expect(analysis.componentTags).toEqual([]);
  });

  it("truncates a long summary line with an ellipsis", () => {
    const analysis = analyzeTaskFileIngestionFailure(
      entry({ error: "x".repeat(200) }),
    );

    expect(analysis.summaryLine).toHaveLength(FILE_ERROR_MAX_LINE_LENGTH);
    expect(analysis.summaryLine.endsWith("…")).toBe(true);
    // The full message stays available for the expanded view.
    expect(analysis.resolvedError).toHaveLength(200);
  });

  it("leaves a short summary line untouched", () => {
    const analysis = analyzeTaskFileIngestionFailure(
      entry({ error: "short message" }),
    );

    expect(analysis.summaryLine).toBe("short message");
  });
});
