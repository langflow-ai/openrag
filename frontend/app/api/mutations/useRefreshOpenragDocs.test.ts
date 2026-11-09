/**
 * Tests for useRefreshOpenragDocs: POSTs the refresh endpoint and, whatever
 * the outcome, invalidates tasks/search/settings so the UI picks up the
 * re-ingested sample docs.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper, createTestQueryClient } from "@/test-utils/render";
import { useRefreshOpenragDocs } from "./useRefreshOpenragDocs";

describe("useRefreshOpenragDocs", () => {
  it("posts to /api/openrag-docs/refresh and resolves with the response", async () => {
    server.use(
      http.post("/api/openrag-docs/refresh", () =>
        HttpResponse.json({ message: "refreshed", refreshed: true }),
      ),
    );

    const { result } = renderHook(() => useRefreshOpenragDocs(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({
      message: "refreshed",
      refreshed: true,
    });
  });

  it("invalidates tasks, search, and settings on settle, even on failure", async () => {
    server.use(
      http.post(
        "/api/openrag-docs/refresh",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    const queryClient = createTestQueryClient();
    queryClient.setDefaultOptions({
      queries: {
        retry: false,
        staleTime: 0,
        gcTime: 60_000,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    });
    const seededKeys = [
      ["tasks", "enhanced"],
      ["search", "results"],
      ["settings"],
    ];
    for (const key of seededKeys) queryClient.setQueryData(key, ["seed"]);

    const { result } = renderHook(() => useRefreshOpenragDocs(), {
      wrapper: createQueryWrapper(queryClient),
    });

    act(() => result.current.mutate());

    await waitFor(() => expect(result.current.isError).toBe(true));
    for (const key of seededKeys) {
      expect(queryClient.getQueryState(key)?.isInvalidated).toBe(true);
    }
  });

  it("uses the response body's detail/error field as the failure message", async () => {
    server.use(
      http.post("/api/openrag-docs/refresh", () =>
        HttpResponse.json(
          { detail: "sample docs already refreshing" },
          {
            status: 409,
          },
        ),
      ),
    );

    const { result } = renderHook(() => useRefreshOpenragDocs(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate());

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe(
      "sample docs already refreshing",
    );
  });

  it("falls back to a plain-text body when the response is not JSON", async () => {
    server.use(
      http.post(
        "/api/openrag-docs/refresh",
        () =>
          new HttpResponse("upstream timed out", {
            status: 504,
            headers: { "content-type": "text/plain" },
          }),
      ),
    );

    const { result } = renderHook(() => useRefreshOpenragDocs(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate());

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("upstream timed out");
  });

  it("falls back to the default message when the body is empty", async () => {
    server.use(
      http.post(
        "/api/openrag-docs/refresh",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useRefreshOpenragDocs(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate());

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe(
      "Failed to refresh OpenRAG docs",
    );
  });
});
