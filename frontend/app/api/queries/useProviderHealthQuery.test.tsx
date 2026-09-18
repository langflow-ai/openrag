import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { authPresets, withAuth } from "@/test-utils/fixtures/auth";
import { makeSettings } from "@/test-utils/fixtures/settings";
import { makeTask, makeTasksResponse } from "@/test-utils/fixtures/task";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper, renderHook, waitFor } from "@/test-utils/render";
import { useProviderHealthQuery } from "./useProviderHealthQuery";

/**
 * `rbacDisabled` is the default auth scenario for this file: it makes
 * `providerHealthAllowed` true unconditionally, which isolates the gate under
 * test (settings.edited / onboarding / active-ingestion) from the separate
 * `providers:read` RBAC gate covered explicitly below.
 */
function wrapper() {
  return createQueryWrapper({
    providers: ["auth", "chat"],
    auth: authPresets.rbacDisabled,
  });
}

describe("useProviderHealthQuery", () => {
  it("stays disabled until settings.edited is true", async () => {
    server.use(
      http.get("/api/settings", () => HttpResponse.json(makeSettings())),
    );

    const { result } = renderHook(() => useProviderHealthQuery(), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isEnabled).toBe(false));
    expect(result.current.data).toBeUndefined();
  });

  it("fetches and returns a healthy response once enabled", async () => {
    server.use(
      http.get("/api/settings", () =>
        HttpResponse.json(makeSettings({ edited: true })),
      ),
      http.get("/api/provider/health", () =>
        HttpResponse.json({
          status: "healthy",
          message: "ok",
          provider: "openai",
        }),
      ),
    );

    const { result } = renderHook(() => useProviderHealthQuery(), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isEnabled).toBe(true));
    await waitFor(() => expect(result.current.data?.status).toBe("healthy"));
  });

  it("maps a 503 to an unhealthy status with the error details", async () => {
    server.use(
      http.get("/api/settings", () =>
        HttpResponse.json(makeSettings({ edited: true })),
      ),
      http.get(
        "/api/provider/health",
        () =>
          new HttpResponse(
            JSON.stringify({
              message: "Provider validation failed",
              provider: "openai",
              llm_error: "Invalid API Key",
            }),
            { status: 503 },
          ),
      ),
    );

    const { result } = renderHook(() => useProviderHealthQuery(), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.data?.status).toBe("unhealthy"));
    expect(result.current.data?.llm_error).toBe("Invalid API Key");
  });

  it("maps any other non-ok status to an error status", async () => {
    server.use(
      http.get("/api/settings", () =>
        HttpResponse.json(makeSettings({ edited: true })),
      ),
      http.get(
        "/api/provider/health",
        () => new HttpResponse(JSON.stringify({}), { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useProviderHealthQuery(), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.data?.status).toBe("error"));
    expect(result.current.data?.message).toBe(
      "Failed to check provider health",
    );
  });

  it("maps a network failure to backend-unavailable", async () => {
    server.use(
      http.get("/api/settings", () =>
        HttpResponse.json(makeSettings({ edited: true })),
      ),
      http.get("/api/provider/health", () => HttpResponse.error()),
    );

    const { result } = renderHook(() => useProviderHealthQuery(), {
      wrapper: wrapper(),
    });

    await waitFor(() =>
      expect(result.current.data?.status).toBe("backend-unavailable"),
    );
  });

  it("stays disabled while a task is pending, running, or processing", async () => {
    server.use(
      http.get("/api/settings", () =>
        HttpResponse.json(makeSettings({ edited: true })),
      ),
      http.get("/api/tasks/enhanced", () =>
        HttpResponse.json(
          makeTasksResponse([makeTask({ task_id: "t1", status: "running" })]),
        ),
      ),
    );

    const { result } = renderHook(() => useProviderHealthQuery(), {
      wrapper: wrapper(),
    });

    await waitFor(() => expect(result.current.isEnabled).toBe(false));
  });

  it("stays disabled without providers:read when RBAC is enforced", async () => {
    server.use(
      http.get("/api/settings", () =>
        HttpResponse.json(makeSettings({ edited: true })),
      ),
    );

    const { result } = renderHook(() => useProviderHealthQuery(), {
      wrapper: createQueryWrapper({
        providers: ["auth", "chat"],
        auth: withAuth(authPresets.viewer, {}),
      }),
    });

    await waitFor(() => expect(result.current.isEnabled).toBe(false));
  });

  it("appends the provider query param when passed", async () => {
    let capturedUrl: string | undefined;
    server.use(
      http.get("/api/settings", () =>
        HttpResponse.json(makeSettings({ edited: true })),
      ),
      http.get("/api/provider/health", ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json({ status: "healthy", message: "ok" });
      }),
    );

    const { result } = renderHook(
      () => useProviderHealthQuery({ provider: "watsonx" }),
      { wrapper: wrapper() },
    );

    await waitFor(() => expect(result.current.data?.status).toBe("healthy"));
    expect(capturedUrl).toContain("provider=watsonx");
  });
});
