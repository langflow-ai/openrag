import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper, renderHook, waitFor } from "@/test-utils/render";
import { useDoclingHealthQuery } from "./useDoclingHealthQuery";

function renderDoclingHealth() {
  return renderHook(() => useDoclingHealthQuery({ retry: false }), {
    wrapper: createQueryWrapper(),
  });
}

describe("useDoclingHealthQuery", () => {
  it("reports healthy on a 200 healthy body", async () => {
    server.use(
      http.get("/api/docling/health", () =>
        HttpResponse.json({ status: "healthy", host: "localhost" }),
      ),
    );

    const { result } = renderDoclingHealth();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ status: "healthy" });
  });

  it("reports degraded when docling-serve is slow to respond", async () => {
    server.use(
      http.get("/api/docling/health", () =>
        HttpResponse.json({
          status: "degraded",
          message: "Docling Serve is slow to respond",
          host: "localhost",
        }),
      ),
    );

    const { result } = renderDoclingHealth();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({
      status: "degraded",
      message: "Docling Serve is slow to respond",
    });
  });

  it("treats a 200 without a JSON body as healthy", async () => {
    server.use(
      http.get(
        "/api/docling/health",
        () => new HttpResponse(null, { status: 200 }),
      ),
    );

    const { result } = renderDoclingHealth();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({ status: "healthy" });
  });

  it("reports unhealthy on a 503", async () => {
    server.use(
      http.get("/api/docling/health", () =>
        HttpResponse.json(
          { status: "unhealthy", message: "Connection timeout" },
          { status: 503 },
        ),
      ),
    );

    const { result } = renderDoclingHealth();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.status).toBe("unhealthy");
  });

  it("reports backend-unavailable when the request itself fails", async () => {
    server.use(http.get("/api/docling/health", () => HttpResponse.error()));

    const { result } = renderDoclingHealth();

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.status).toBe("backend-unavailable");
  });
});
