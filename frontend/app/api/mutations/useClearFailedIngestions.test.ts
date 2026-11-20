/**
 * Tests for useClearFailedIngestions: the "Retry" / "Retry all" mutation that
 * forgets failures so the next sync attempts the files again.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper, createTestQueryClient } from "@/test-utils/render";
import { FAILED_INGESTIONS_QUERY_KEY } from "../queries/useFailedIngestionsQuery";
import { useClearFailedIngestions } from "./useClearFailedIngestions";

describe("useClearFailedIngestions", () => {
  it("posts the connector type and file id for a single retry", async () => {
    let body: unknown;
    server.use(
      http.post(
        "/api/connectors/failed-ingestions/clear",
        async ({ request }) => {
          body = await request.json();
          return HttpResponse.json({ cleared: 1 });
        },
      ),
    );

    const { result } = renderHook(() => useClearFailedIngestions(), {
      wrapper: createQueryWrapper(),
    });

    act(() =>
      result.current.mutate({
        connectorType: "aws_s3",
        fileId: "bucket::docs/broken.docx",
      }),
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ cleared: 1 });
    expect(body).toEqual({
      connector_type: "aws_s3",
      file_id: "bucket::docs/broken.docx",
    });
  });

  it("posts an empty selection to clear every failure", async () => {
    let body: unknown;
    server.use(
      http.post(
        "/api/connectors/failed-ingestions/clear",
        async ({ request }) => {
          body = await request.json();
          return HttpResponse.json({ cleared: 4 });
        },
      ),
    );

    const { result } = renderHook(() => useClearFailedIngestions(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate({}));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.cleared).toBe(4);
    expect(body).toEqual({});
  });

  it("throws the backend's error message when the response is not ok", async () => {
    server.use(
      http.post("/api/connectors/failed-ingestions/clear", () =>
        HttpResponse.json(
          { error: "connector_type is required with file_id" },
          { status: 400 },
        ),
      ),
    );

    const { result } = renderHook(() => useClearFailedIngestions(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate({ fileId: "x" }));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe(
      "connector_type is required with file_id",
    );
  });

  it("falls back to a default message when the error body has no error field", async () => {
    server.use(
      http.post("/api/connectors/failed-ingestions/clear", () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useClearFailedIngestions(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate({}));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe(
      "Failed to clear failed documents",
    );
  });

  it("invalidates the failed-ingestions list once the request settles", async () => {
    server.use(
      http.post("/api/connectors/failed-ingestions/clear", () =>
        HttpResponse.json({ cleared: 1 }),
      ),
    );
    const queryClient = createTestQueryClient();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    const { result } = renderHook(() => useClearFailedIngestions(), {
      wrapper: createQueryWrapper({ queryClient }),
    });

    act(() => result.current.mutate({}));

    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: FAILED_INGESTIONS_QUERY_KEY,
      }),
    );
  });
});
