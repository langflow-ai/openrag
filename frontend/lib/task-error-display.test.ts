import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { TaskFileEntry } from "@/app/api/queries/useGetTasksQuery";
import { resolveTaskFileError } from "@/lib/task-error-display";

// A real _update_by_query 409 as opensearch-py renders it: the whole response
// body becomes the exception message, because that response carries no
// top-level "error" key for the client to use instead.
const OPENSEARCH_CONFLICT_ERROR =
  'ConflictError(409, \'{"took":2719,"timed_out":false,"total":300,' +
  '"updated":19,"version_conflicts":1,"failures":[{"index":"documents",' +
  '"id":"20","cause":{"type":"version_conflict_engine_exception"}}]}\')';

const BACKEND_CLASSIFIED_MESSAGE =
  "The search index was busy and this change conflicted with another " +
  "update. Nothing is wrong with the file — retry ingestion.";

describe("resolveTaskFileError", () => {
  it("prefers the backend's user_facing_message over the raw error", () => {
    // This precedence is what makes the backend classifier work at all. If these
    // checks are ever reordered, a classified OpenSearch failure would fall back
    // to the raw payload and be mangled again.
    const entry: TaskFileEntry = {
      status: "failed",
      error: OPENSEARCH_CONFLICT_ERROR,
      user_facing_message: BACKEND_CLASSIFIED_MESSAGE,
    };

    assert.equal(resolveTaskFileError(entry), BACKEND_CLASSIFIED_MESSAGE);
  });

  it("passes a clean sentence through the provider parser unchanged", () => {
    // The message contains no JSON, so the chat provider-error parser must not
    // rewrite or truncate it.
    const entry: TaskFileEntry = {
      status: "failed",
      user_facing_message: BACKEND_CLASSIFIED_MESSAGE,
    };

    assert.equal(resolveTaskFileError(entry), BACKEND_CLASSIFIED_MESSAGE);
  });

  it("keeps the whole raw error when the backend did not classify it", () => {
    // Regression guard: this used to collapse to the 20-character fragment
    // "ConflictError(409, '", discarding the failures[] array that names the
    // index, shard and document — the only way to diagnose the failure.
    const entry: TaskFileEntry = {
      status: "failed",
      error: OPENSEARCH_CONFLICT_ERROR,
    };

    const resolved = resolveTaskFileError(entry);
    assert.equal(resolved, OPENSEARCH_CONFLICT_ERROR);
    assert.ok(resolved.includes("version_conflict_engine_exception"));
  });

  it("still prefers a result warning over everything else", () => {
    const entry: TaskFileEntry = {
      status: "skipped",
      error: OPENSEARCH_CONFLICT_ERROR,
      user_facing_message: BACKEND_CLASSIFIED_MESSAGE,
      result: {
        warning: "File no longer exists at source; removed from index.",
      },
    };

    assert.equal(
      resolveTaskFileError(entry),
      "File no longer exists at source; removed from index.",
    );
  });

  it("falls back to the task-level error, then to Unknown error", () => {
    assert.equal(
      resolveTaskFileError({ status: "failed" }, "task blew up"),
      "task blew up",
    );
    assert.equal(resolveTaskFileError({ status: "failed" }), "Unknown error");
  });
});
