/**
 * Tests for useGetNudgesQuery: gated on onboarding completion and LLM
 * health, and parses the backend's newline-delimited `response` string into
 * a list of nudges.
 *
 * The default settings/tasks handlers (see test-utils/msw/handlers.ts) leave
 * onboarding finished and provider health disabled (settings.edited is
 * falsy), so `useProviderHealthQuery` never fetches and `isLLMHealthy` stays
 * optimistically true without mocking /api/provider/health.
 */
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { makeSettings } from "@/test-utils/fixtures/settings";
import { server } from "@/test-utils/msw/server";
import {
  createQueryWrapper,
  createTestQueryClient,
  renderHook,
  waitFor,
} from "@/test-utils/render";
import { useGetNudgesQuery } from "./useGetNudgesQuery";

describe("useGetNudgesQuery", () => {
  it("splits the newline-delimited response into nudges", async () => {
    server.use(
      http.post("/api/nudges", () =>
        HttpResponse.json({ response: "Try uploading a PDF\nAsk about X\n" }),
      ),
    );

    const { result } = renderHook(() => useGetNudgesQuery(), {
      wrapper: createQueryWrapper({ providers: ["auth", "chat"] }),
    });

    await waitFor(() =>
      expect(result.current.data).toEqual([
        "Try uploading a PDF",
        "Ask about X",
      ]),
    );
  });

  it("returns an empty list when the response has no response field", async () => {
    server.use(http.post("/api/nudges", () => HttpResponse.json({})));

    const { result } = renderHook(() => useGetNudgesQuery(), {
      wrapper: createQueryWrapper({ providers: ["auth", "chat"] }),
    });

    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data).toEqual([]);
  });

  it("swallows a non-abort error and returns an empty list instead of throwing", async () => {
    server.use(
      http.post("/api/nudges", () => new HttpResponse(null, { status: 500 })),
    );

    const { result } = renderHook(() => useGetNudgesQuery(), {
      wrapper: createQueryWrapper({ providers: ["auth", "chat"] }),
    });

    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.isError).toBe(false);
    expect(result.current.data).toEqual([]);
  });

  it("includes the chatId in the request path when given", async () => {
    let capturedUrl = "";
    server.use(
      http.post("/api/nudges/chat-123", ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json({ response: "" });
      }),
    );

    const { result } = renderHook(
      () => useGetNudgesQuery({ chatId: "chat-123" }),
      { wrapper: createQueryWrapper({ providers: ["auth", "chat"] }) },
    );

    await waitFor(() => expect(capturedUrl).not.toBe(""));
    expect(capturedUrl).toContain("/api/nudges/chat-123");
  });

  it("stays disabled while onboarding is still in progress", async () => {
    let nudgeRequests = 0;
    server.use(
      http.get("/api/settings", () =>
        HttpResponse.json(makeSettings({ onboarding: { current_step: 1 } })),
      ),
      http.post("/api/nudges", () => {
        nudgeRequests += 1;
        return HttpResponse.json({ response: "x" });
      }),
    );

    const queryClient = createTestQueryClient();
    const { result } = renderHook(() => useGetNudgesQuery(), {
      wrapper: createQueryWrapper({ queryClient, providers: ["auth", "chat"] }),
    });

    // Wait for the in-progress onboarding settings to resolve and propagate
    // to chat state, rather than sleeping for a fixed interval.
    await waitFor(() =>
      expect(
        (
          queryClient.getQueryData(["settings"]) as
            | ReturnType<typeof makeSettings>
            | undefined
        )?.onboarding?.current_step,
      ).toBe(1),
    );
    await waitFor(() =>
      expect(queryClient.isFetching({ queryKey: ["settings"] })).toBe(0),
    );

    // Query is disabled: no request, no data, not loading.
    expect(nudgeRequests).toBe(0);
    expect(result.current.data).toBeUndefined();
    expect(result.current.isLoading).toBe(false);
  });

  it("cancel() drops the cached entry from the query client", async () => {
    server.use(
      http.post("/api/nudges", () =>
        HttpResponse.json({ response: "Try this" }),
      ),
    );

    const queryClient = createTestQueryClient();
    const nudgesKey = ["nudges", undefined, undefined, undefined, undefined];

    const { result } = renderHook(() => useGetNudgesQuery(), {
      wrapper: createQueryWrapper({ queryClient, providers: ["auth", "chat"] }),
    });

    await waitFor(() => expect(result.current.data).toEqual(["Try this"]));
    expect(queryClient.getQueryData(nudgesKey)).toEqual(["Try this"]);

    result.current.cancel();

    expect(queryClient.getQueryData(nudgesKey)).toBeUndefined();
  });
});
