import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { useAuth } from "@/contexts/auth-context";
import { authPresets, withAuth } from "@/test-utils/fixtures/auth";
import { makeSettings } from "@/test-utils/fixtures/settings";
import { makeTask, makeTasksResponse } from "@/test-utils/fixtures/task";
import { server } from "@/test-utils/msw/server";
import {
  createQueryWrapper,
  createTestQueryClient,
  renderHook,
  waitFor,
} from "@/test-utils/render";
import { useGetSettingsQuery } from "./useGetSettingsQuery";
import { useGetTasksQuery } from "./useGetTasksQuery";
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
    let healthRequests = 0;
    server.use(
      http.get("/api/settings", () => HttpResponse.json(makeSettings())),
      http.get("/api/provider/health", () => {
        healthRequests++;
        return HttpResponse.json({ status: "healthy", message: "ok" });
      }),
    );

    const queryClient = createTestQueryClient();
    const { result } = renderHook(
      () => ({
        health: useProviderHealthQuery(),
        settings: useGetSettingsQuery(),
        tasks: useGetTasksQuery(),
      }),
      {
        wrapper: createQueryWrapper({
          providers: ["auth", "chat"],
          auth: authPresets.rbacDisabled,
          queryClient,
        }),
      },
    );

    await waitFor(() => expect(result.current.settings.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.tasks.isSuccess).toBe(true));
    expect(result.current.settings.data?.edited).toBeFalsy();
    expect(result.current.health.isEnabled).toBe(false);
    expect(result.current.health.data).toBeUndefined();
    expect(healthRequests).toBe(0);
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

  it.each([
    "pending",
    "running",
    "processing",
  ] as const)("stays disabled while a task is %s", async (status) => {
    let healthRequests = 0;
    let releaseSettings!: () => void;
    const settingsBlocked = new Promise<void>((resolve) => {
      releaseSettings = resolve;
    });
    server.use(
      http.get("/api/settings", async () => {
        await settingsBlocked;
        return HttpResponse.json(makeSettings({ edited: true }));
      }),
      http.get("/api/tasks/enhanced", () => {
        return HttpResponse.json(
          makeTasksResponse([makeTask({ task_id: "t1", status })]),
        );
      }),
      http.get("/api/provider/health", () => {
        healthRequests++;
        return HttpResponse.json({ status: "healthy", message: "ok" });
      }),
    );

    const queryClient = createTestQueryClient();
    const { result } = renderHook(
      () => ({
        health: useProviderHealthQuery(),
        settings: useGetSettingsQuery(),
        tasks: useGetTasksQuery(),
      }),
      {
        wrapper: createQueryWrapper({
          providers: ["auth", "chat"],
          auth: authPresets.rbacDisabled,
          queryClient,
        }),
      },
    );

    await waitFor(() =>
      expect(result.current.tasks.data).toEqual([
        expect.objectContaining({ status }),
      ]),
    );
    releaseSettings();
    await waitFor(() =>
      expect(result.current.settings.data?.edited).toBe(true),
    );
    expect(result.current.health.isEnabled).toBe(false);
    expect(healthRequests).toBe(0);
  });

  it("stays disabled without providers:read when RBAC is enforced", async () => {
    let healthRequests = 0;
    server.use(
      http.get("/api/settings", () =>
        HttpResponse.json(makeSettings({ edited: true })),
      ),
      http.get("/api/provider/health", () => {
        healthRequests++;
        return HttpResponse.json({ status: "healthy", message: "ok" });
      }),
    );

    const queryClient = createTestQueryClient();
    const { result } = renderHook(
      () => ({
        health: useProviderHealthQuery(),
        auth: useAuth(),
        settings: useGetSettingsQuery(),
        tasks: useGetTasksQuery(),
      }),
      {
        wrapper: createQueryWrapper({
          providers: ["auth", "chat"],
          auth: withAuth(authPresets.viewer, {}),
          queryClient,
        }),
      },
    );

    await waitFor(() =>
      expect(result.current.auth.permissionsResolved).toBe(true),
    );
    await waitFor(() =>
      expect(result.current.settings.data?.edited).toBe(true),
    );
    await waitFor(() => expect(result.current.tasks.isSuccess).toBe(true));
    expect(result.current.health.isEnabled).toBe(false);
    expect(healthRequests).toBe(0);
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
