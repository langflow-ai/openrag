import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import { server } from "@/test-utils/msw/server";
import {
  act,
  createQueryWrapper,
  renderHook,
  waitFor,
} from "@/test-utils/render";
import { useGetNudgesQuery } from "./useGetNudgesQuery";

describe("useGetNudgesQuery", () => {
  it("refreshes nudges when a completed turn keeps the same conversation id", async () => {
    let requests = 0;
    server.use(
      http.get("/api/provider/health", () =>
        HttpResponse.json({ status: "healthy", message: "ok" }),
      ),
      http.post("/api/nudges/conversation-1", () => {
        requests += 1;
        return HttpResponse.json({
          response: requests === 1 ? "First suggestion" : "Next suggestion",
        });
      }),
    );

    const { result } = renderHook(
      () => useGetNudgesQuery({ chatId: "conversation-1" }),
      {
        wrapper: createQueryWrapper({
          providers: ["auth", "chat"],
          auth: authPresets.noAuthMode,
        }),
      },
    );

    await waitFor(() =>
      expect(result.current.data).toEqual(["First suggestion"]),
    );

    act(() => result.current.refresh());

    await waitFor(() => expect(requests).toBe(2));
    expect(result.current.data).toEqual(["Next suggestion"]);
  });
});
