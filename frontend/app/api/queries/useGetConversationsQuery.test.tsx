import axios from "axios";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper, renderHook, waitFor } from "@/test-utils/render";
import { useGetConversationsQuery } from "./useGetConversationsQuery";

describe("useGetConversationsQuery", () => {
  it("returns conversations sorted by last_activity", async () => {
    server.use(
      http.get("/api/chat/history", () =>
        HttpResponse.json({
          conversations: [
            {
              response_id: "a",
              title: "A",
              endpoint: "chat",
              messages: [],
              total_messages: 0,
              last_activity: "2024-01-02T00:00:00Z",
            },
            {
              response_id: "b",
              title: "B",
              endpoint: "chat",
              messages: [],
              total_messages: 0,
              last_activity: "2024-01-01T00:00:00Z",
            },
          ],
        }),
      ),
    );

    const { result } = renderHook(() => useGetConversationsQuery("chat"), {
      wrapper: createQueryWrapper({ providers: ["auth", "chat"] }),
    });

    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data?.map((c) => c.response_id)).toEqual(["a", "b"]);
  });

  it("returns empty list on a server error without throwing", async () => {
    server.use(
      http.get(
        "/api/chat/history",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    try {
      const { result } = renderHook(() => useGetConversationsQuery("chat"), {
        wrapper: createQueryWrapper({ providers: ["auth", "chat"] }),
      });

      await waitFor(() => expect(result.current.data).toBeDefined());
      expect(result.current.isError).toBe(false);
      expect(result.current.data).toEqual([]);
      // Unlike a cancellation, a real failure is still logged.
      expect(consoleSpy).toHaveBeenCalledWith(
        expect.stringContaining("Failed to fetch conversations"),
      );
    } finally {
      consoleSpy.mockRestore();
    }
  });

  it("swallows an axios CanceledError and returns an empty list", async () => {
    // Use mockImplementation with a URL check so the spy only rejects for the
    // history endpoint — settings/auth GETs must still reach MSW.
    const originalGet = apiClient.get.bind(apiClient);
    const getSpy = vi
      .spyOn(apiClient, "get")
      .mockImplementation((url, config) => {
        if (typeof url === "string" && url.includes("/history")) {
          return Promise.reject(new axios.CanceledError("canceled"));
        }
        return originalGet(url as string, config);
      });
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    try {
      const { result } = renderHook(() => useGetConversationsQuery("chat"), {
        wrapper: createQueryWrapper({ providers: ["auth", "chat"] }),
      });

      await waitFor(() => expect(result.current.data).toBeDefined());
      expect(result.current.isError).toBe(false);
      expect(result.current.data).toEqual([]);
      expect(consoleSpy).not.toHaveBeenCalledWith(
        expect.stringContaining("conversations"),
        expect.any(Error),
      );
    } finally {
      consoleSpy.mockRestore();
      getSpy.mockRestore();
    }
  });
});
