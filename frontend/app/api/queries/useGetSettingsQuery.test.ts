import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper, renderHook, waitFor } from "@/test-utils/render";
import { useGetSettingsQuery } from "./useGetSettingsQuery";

describe("useGetSettingsQuery", () => {
  it("resolves /api/settings and returns the parsed body", async () => {
    server.use(
      http.get("/api/settings", () =>
        HttpResponse.json({
          langflow_url: "http://localhost:7860",
          edited: true,
        }),
      ),
    );

    const { result } = renderHook(() => useGetSettingsQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({
      langflow_url: "http://localhost:7860",
      edited: true,
    });
  });

  it("throws a fixed error message when the backend responds non-ok", async () => {
    server.use(
      http.get("/api/settings", () => new HttpResponse(null, { status: 500 })),
    );

    const { result } = renderHook(() => useGetSettingsQuery(), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Failed to fetch settings");
  });
});
