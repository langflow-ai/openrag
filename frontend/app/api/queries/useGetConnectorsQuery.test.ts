/**
 * Tests for useGetConnectorsQuery: fetching connector definitions, resolving
 * each one's per-type status, and filtering by deployment/workspace policy.
 *
 * `brand` pulls in `auth` automatically (see test-utils/render.tsx), and the
 * default scenario (oss brand, non-IBM auth) exercises the plain
 * `isConnectorTypeVisible` filter without touching the workspace-policy
 * fetch — that path gets its own test with an IBM auth scenario.
 */
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper, renderHook, waitFor } from "@/test-utils/render";
import {
  useGetConnectorAccessQuery,
  useGetConnectorsQuery,
  useUpdateConnectorAccessMutation,
} from "./useGetConnectorsQuery";

function connectorsPayload(
  connectors: Record<string, Record<string, unknown>>,
) {
  return { connectors };
}

describe("useGetConnectorsQuery", () => {
  it("marks a connector connected from an active, authenticated connection", async () => {
    server.use(
      http.get("/api/connectors", () =>
        HttpResponse.json(
          connectorsPayload({
            google_drive: {
              name: "Google Drive",
              description: "desc",
              icon: "google",
              kind: "oauth",
              available: true,
            },
          }),
        ),
      ),
      http.get("/api/connectors/google_drive/status", () =>
        HttpResponse.json({
          connections: [
            {
              connection_id: "conn-1",
              is_active: true,
              is_authenticated: true,
              created_at: "2026-01-01T00:00:00Z",
              client_id: "client-1",
              base_url: "https://drive.example.com",
            },
          ],
        }),
      ),
    );

    const { result } = renderHook(() => useGetConnectorsQuery(), {
      wrapper: createQueryWrapper({ providers: ["brand"] }),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([
      expect.objectContaining({
        id: "google_drive",
        status: "connected",
        connectionId: "conn-1",
        clientId: "client-1",
        requiresOAuth: true,
      }),
    ]);
  });

  it("marks an oauth connector configured when only env credentials exist", async () => {
    server.use(
      http.get("/api/connectors", () =>
        HttpResponse.json(
          connectorsPayload({
            onedrive: {
              name: "OneDrive",
              description: "desc",
              icon: "onedrive",
              kind: "oauth",
              available: true,
            },
          }),
        ),
      ),
      http.get("/api/connectors/onedrive/status", () =>
        HttpResponse.json({ connections: [], has_env_credentials: true }),
      ),
    );

    const { result } = renderHook(() => useGetConnectorsQuery(), {
      wrapper: createQueryWrapper({ providers: ["brand"] }),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0].status).toBe("configured");
  });

  it("defaults to not_connected when the status request itself fails", async () => {
    server.use(
      http.get("/api/connectors", () =>
        HttpResponse.json(
          connectorsPayload({
            google_drive: {
              name: "Google Drive",
              description: "desc",
              icon: "google",
              kind: "oauth",
              available: true,
            },
          }),
        ),
      ),
      http.get(
        "/api/connectors/google_drive/status",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useGetConnectorsQuery(), {
      wrapper: createQueryWrapper({ providers: ["brand"] }),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.[0].status).toBe("not_connected");
  });

  it("marks an always-connected managed connector connected without OAuth", async () => {
    server.use(
      http.get("/api/connectors", () =>
        HttpResponse.json(
          connectorsPayload({
            url: {
              name: "URL",
              description: "Crawl websites",
              icon: "url",
              kind: "managed",
              always_connected: true,
              available: true,
            },
          }),
        ),
      ),
      http.get("/api/connectors/url/status", () =>
        HttpResponse.json({ connections: [] }),
      ),
    );

    const { result } = renderHook(() => useGetConnectorsQuery(), {
      wrapper: createQueryWrapper({ providers: ["brand"] }),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual([
      expect.objectContaining({
        id: "url",
        status: "connected",
        requiresOAuth: false,
        alwaysConnected: true,
      }),
    ]);
  });

  it("filters out aws_s3 and ibm_cos for a non-IBM oss deployment", async () => {
    server.use(
      http.get("/api/connectors", () =>
        HttpResponse.json(
          connectorsPayload({
            google_drive: {
              name: "Google Drive",
              description: "desc",
              icon: "google",
              kind: "oauth",
              available: true,
            },
            aws_s3: {
              name: "AWS S3",
              description: "desc",
              icon: "aws",
              kind: "bucket",
              available: true,
            },
            ibm_cos: {
              name: "IBM COS",
              description: "desc",
              icon: "ibm",
              kind: "bucket",
              available: true,
            },
          }),
        ),
      ),
      http.get(/\/api\/connectors\/.+\/status/, () =>
        HttpResponse.json({ connections: [] }),
      ),
    );

    const { result } = renderHook(() => useGetConnectorsQuery(), {
      wrapper: createQueryWrapper({ providers: ["brand"] }),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.map((c) => c.id)).toEqual(["google_drive"]);
  });

  it("applies workspace policy access instead of deployment visibility under IBM auth", async () => {
    server.use(
      http.get("/api/connectors", () =>
        HttpResponse.json(
          connectorsPayload({
            google_drive: {
              name: "Google Drive",
              description: "desc",
              icon: "google",
              kind: "oauth",
              available: true,
            },
            onedrive: {
              name: "OneDrive",
              description: "desc",
              icon: "onedrive",
              kind: "oauth",
              available: true,
            },
          }),
        ),
      ),
      http.get(/\/api\/connectors\/.+\/status/, () =>
        HttpResponse.json({ connections: [] }),
      ),
      http.get("/api/connectors/workspace-policy", () =>
        HttpResponse.json({ access: { onedrive: false } }),
      ),
    );

    const { result } = renderHook(() => useGetConnectorsQuery(), {
      wrapper: createQueryWrapper({
        providers: ["brand"],
        auth: authPresets.ibmAuthMode,
      }),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    // onedrive explicitly denied by the workspace; google_drive falls back to
    // isConnectorTypeVisible, which is true for a non-onedrive/non-bucket type.
    expect(result.current.data?.map((c) => c.id)).toEqual(["google_drive"]);
  });
});

describe("useGetConnectorAccessQuery", () => {
  it("filters the returned list by deployment visibility", async () => {
    server.use(
      http.get("/api/connectors/user-access", () =>
        HttpResponse.json({
          connectors: [
            { type: "google_drive", name: "Google Drive", enabled: true },
            { type: "aws_s3", name: "AWS S3", enabled: true },
          ],
        }),
      ),
    );

    const { result } = renderHook(() => useGetConnectorAccessQuery(), {
      wrapper: createQueryWrapper({ providers: ["brand"] }),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.map((c) => c.type)).toEqual(["google_drive"]);
  });

  it("throws when the request fails", async () => {
    server.use(
      http.get(
        "/api/connectors/user-access",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useGetConnectorAccessQuery(), {
      wrapper: createQueryWrapper({ providers: ["brand"] }),
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toMatch(
      /Failed to fetch connectors permission/,
    );
  });
});

describe("useUpdateConnectorAccessMutation", () => {
  it("PUTs the access map and returns the filtered, updated list", async () => {
    let capturedBody: unknown;
    server.use(
      http.put("/api/connectors/user-access", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({
          connectors: [
            { type: "google_drive", name: "Google Drive", enabled: false },
          ],
        });
      }),
    );

    const { result } = renderHook(() => useUpdateConnectorAccessMutation(), {
      wrapper: createQueryWrapper({ providers: ["brand"] }),
    });

    result.current.mutate({ google_drive: false });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedBody).toEqual({ access: { google_drive: false } });
    expect(result.current.data?.[0].enabled).toBe(false);
  });

  it("throws the backend's error message on failure", async () => {
    server.use(
      http.put("/api/connectors/user-access", () =>
        HttpResponse.json({ error: "not allowed" }, { status: 403 }),
      ),
    );

    const { result } = renderHook(() => useUpdateConnectorAccessMutation(), {
      wrapper: createQueryWrapper({ providers: ["brand"] }),
    });

    result.current.mutate({ google_drive: false });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("not allowed");
  });
});
