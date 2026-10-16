import { renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper } from "@/test-utils/render";
import { useUploadHistogram } from "./useUploadHistogram";

const baseParams = {
  start: "2024-05-01T00:00:00.000Z",
  end: "2024-06-20T23:59:59.999Z",
  tz: "America/New_York",
};

describe("useUploadHistogram", () => {
  it("sends the window, time zone and filters", async () => {
    let capturedUrl: string | undefined;
    server.use(
      http.get("/api/files/upload-histogram", ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json({ total: 3, days: { "2024-06-01": 3 } });
      }),
    );

    const { result } = renderHook(
      () =>
        useUploadHistogram({
          ...baseParams,
          connectorType: ["local"],
          mimetype: ["application/pdf"],
          owner: ["u1", "u2"],
          dataSources: ["a.pdf"],
        }),
      { wrapper: createQueryWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    const url = new URL(capturedUrl!);
    expect(url.searchParams.get("start")).toBe(baseParams.start);
    expect(url.searchParams.get("end")).toBe(baseParams.end);
    expect(url.searchParams.get("tz")).toBe("America/New_York");
    expect(url.searchParams.getAll("connector_type")).toEqual(["local"]);
    expect(url.searchParams.getAll("mimetype")).toEqual(["application/pdf"]);
    expect(url.searchParams.getAll("owner")).toEqual(["u1", "u2"]);
    expect(url.searchParams.getAll("data_sources")).toEqual(["a.pdf"]);
    expect(result.current.data).toEqual({
      total: 3,
      days: { "2024-06-01": 3 },
    });
  });

  it("defaults missing fields", async () => {
    server.use(
      http.get("/api/files/upload-histogram", () => HttpResponse.json({})),
    );
    const { result } = renderHook(() => useUploadHistogram(baseParams), {
      wrapper: createQueryWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ total: 0, days: {} });
  });

  it("surfaces server errors", async () => {
    server.use(
      http.get("/api/files/upload-histogram", () =>
        HttpResponse.json({ error: "boom" }, { status: 500 }),
      ),
    );
    const { result } = renderHook(() => useUploadHistogram(baseParams), {
      wrapper: createQueryWrapper(),
    });
    await waitFor(() => expect(result.current.isError).toBe(true));
  });
});
