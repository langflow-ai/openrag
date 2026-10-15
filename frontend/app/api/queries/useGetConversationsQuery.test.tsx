import axios from "axios";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
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

    const { result } = renderHook(() => useGetConversationsQuery("chat"), {
      wrapper: createQueryWrapper({ providers: ["auth", "chat"] }),
    });

    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.isError).toBe(false);
    expect(result.current.data).toEqual([]);
  });

  it("swallows an axios CanceledError and returns an empty list", async () => {
    server.use(
      http.get("/api/chat/history", () => {
        throw new axios.CanceledError("canceled");
      }),
    );

    const consoleSpy = vi.spyOn(console, "error");

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
    consoleSpy.mockRestore();
  });
});
