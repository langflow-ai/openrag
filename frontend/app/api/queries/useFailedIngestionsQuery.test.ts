/**
 * Tests for useFailedIngestionsQuery: it loads the user's failed documents
 * from GET /api/connectors/failed-ingestions and surfaces the backend's error.
 */
import { renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper } from "@/test-utils/render";
import {
  FAILED_INGESTIONS_QUERY_KEY,
  useFailedIngestionsQuery,
} from "./useFailedIngestionsQuery";

const failure = {
  connector_type: "aws_s3",
  file_id: "bucket::docs/broken.docx",
  filename: "broken.docx",
  last_error: "corrupt file",
  attempt_count: 3,
  skipped: true,
  first_failed_at: "2026-01-01T00:00:00+00:00",
  last_failed_at: "2026-01-02T00:00:00+00:00",
};

describe("useFailedIngestionsQuery", () => {
  it("resolves with the failures and the retry budget", async () => {
    server.use(
      http.get("/api/connectors/failed-ingestions", () =>
        HttpResponse.json({ max_attempts: 3, failures: [failure] }),
      ),
    );

    const { result } = renderHook(() => useFailedIngestionsQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.max_attempts).toBe(3);
    expect(result.current.data?.failures).toEqual([failure]);
  });

  it("resolves with an empty list when nothing has failed", async () => {
    server.use(
      http.get("/api/connectors/failed-ingestions", () =>
        HttpResponse.json({ max_attempts: 3, failures: [] }),
      ),
    );

    const { result } = renderHook(() => useFailedIngestionsQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.failures).toEqual([]);
  });

  it("throws the backend's error message when the response is not ok", async () => {
    server.use(
      http.get("/api/connectors/failed-ingestions", () =>
        HttpResponse.json(
          { error: "Could not list failed documents" },
          { status: 500 },
        ),
      ),
    );

    const { result } = renderHook(() => useFailedIngestionsQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe(
      "Could not list failed documents",
    );
  });

  it("falls back to a default message when the error body has no error field", async () => {
    server.use(
      http.get("/api/connectors/failed-ingestions", () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useFailedIngestionsQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe(
      "Failed to load failed documents",
    );
  });

  it("does not fetch while disabled", async () => {
    let requests = 0;
    server.use(
      http.get("/api/connectors/failed-ingestions", () => {
        requests += 1;
        return HttpResponse.json({ max_attempts: 3, failures: [] });
      }),
    );

    const { result } = renderHook(
      () => useFailedIngestionsQuery({ enabled: false }),
      { wrapper: createQueryWrapper() },
    );

    // Let any (unexpected) request settle before asserting none was made.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(result.current.fetchStatus).toBe("idle");
    expect(requests).toBe(0);
  });

  it("exposes a stable query key for invalidation", () => {
    expect(FAILED_INGESTIONS_QUERY_KEY).toEqual(["failed-ingestions"]);
  });
});
