import { HttpResponse, http } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";
import { server } from "@/test-utils/msw/server";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("apiClient", () => {
  it("sends requests through Axios below Next's basePath", async () => {
    vi.stubEnv("NEXT_PUBLIC_OPENRAG_FRONTEND_BASE_PATH", "/openrag-fe");
    const seen = vi.fn();
    server.use(
      http.get("/openrag-fe/api/status", ({ request }) => {
        seen(request.url);
        return HttpResponse.json({ healthy: true });
      }),
    );

    const { apiClient } = await import("./api-client");
    const response = await apiClient.get("/status");

    expect(response.status).toBe(200);
    expect(response.data).toEqual({ healthy: true });
    expect(seen).toHaveBeenCalledWith(
      "http://localhost:3000/openrag-fe/api/status",
    );
  });

  it("does not treat a non-2xx response as a transport failure", async () => {
    vi.stubEnv("NEXT_PUBLIC_OPENRAG_FRONTEND_BASE_PATH", "/openrag-fe");
    server.use(
      http.get("/openrag-fe/api/forbidden", () =>
        HttpResponse.json({ error: "forbidden" }, { status: 403 }),
      ),
    );
    const { apiClient } = await import("./api-client");
    const response = await apiClient.get("/forbidden");

    expect(response.status).toBe(403);
    expect(response.data).toEqual({ error: "forbidden" });
  });

  it("does not use the API base URL for absolute third-party URLs", async () => {
    const { apiClient } = await import("./api-client");
    expect(
      apiClient.getUri({ url: "https://graph.microsoft.com/v1.0/me" }),
    ).toBe("https://graph.microsoft.com/v1.0/me");
  });
});
