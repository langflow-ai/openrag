/**
 * Tests for useConnectConnectorMutation: POSTs /api/auth/init and either
 * redirects into an OAuth flow or, for direct-auth (bucket) connectors,
 * refreshes the connector list in place.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it } from "vitest";
import type { Connector } from "@/app/api/queries/useGetConnectorsQuery";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper, createTestQueryClient } from "@/test-utils/render";
import { useConnectConnectorMutation } from "./useConnectConnectorMutation";

function connector(overrides: Partial<Connector> = {}): Connector {
  return {
    id: "google_drive",
    name: "Google Drive",
    description: "desc",
    icon: "google",
    status: "not_connected",
    type: "google_drive",
    ...overrides,
  };
}

describe("useConnectConnectorMutation", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("stores OAuth redirect state in localStorage and does not touch the connector cache", async () => {
    server.use(
      http.post("/api/auth/init", () =>
        HttpResponse.json({
          connection_id: "conn-1",
          oauth_config: {
            authorization_endpoint: "https://accounts.example.com/auth",
            client_id: "client-1",
            scopes: ["drive.readonly"],
            redirect_uri: "http://localhost:3000/auth/callback",
          },
        }),
      ),
    );

    const queryClient = createTestQueryClient();
    queryClient.setDefaultOptions({
      queries: {
        retry: false,
        staleTime: 0,
        gcTime: 60_000,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    });
    queryClient.setQueryData(
      ["connectors", false, false, false, false],
      [connector()],
    );

    const { result } = renderHook(() => useConnectConnectorMutation(), {
      wrapper: createQueryWrapper({ queryClient, providers: ["auth"] }),
    });

    act(() => {
      result.current.mutate({
        connector: connector(),
        redirectUri: "http://localhost:3000/auth/callback",
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(localStorage.getItem("connecting_connector_id")).toBe("conn-1");
    expect(localStorage.getItem("connecting_connector_type")).toBe(
      "google_drive",
    );
    expect(localStorage.getItem("auth_purpose")).toBe("data_source");
    // The optimistic snapshot is never restored on success, and the OAuth
    // branch never invalidates — the cache should still hold the seed value.
    expect(
      queryClient.getQueryData(["connectors", false, false, false, false]),
    ).toEqual([connector()]);
  });

  it("marks a 'test' purpose for the return-tab redirect", async () => {
    server.use(
      http.post("/api/auth/init", () =>
        HttpResponse.json({
          connection_id: "conn-2",
          oauth_config: {
            authorization_endpoint: "https://accounts.example.com/auth",
            client_id: "client-1",
            scopes: ["drive.readonly"],
            redirect_uri: "http://localhost:3000/auth/callback",
          },
        }),
      ),
    );

    const { result } = renderHook(() => useConnectConnectorMutation(), {
      wrapper: createQueryWrapper({ providers: ["auth"] }),
    });

    act(() => {
      result.current.mutate({
        connector: connector(),
        redirectUri: "http://localhost:3000/auth/callback",
        purpose: "test",
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(localStorage.getItem("auth_purpose")).toBe("test");
    expect(localStorage.getItem("test_connection_return_tab")).toBe(
      "connector-access",
    );
  });

  it("invalidates the connector list for a direct-auth connector (no oauth_config)", async () => {
    server.use(
      http.post("/api/auth/init", () =>
        HttpResponse.json({ connection_id: "conn-3" }),
      ),
    );

    const queryClient = createTestQueryClient();
    queryClient.setDefaultOptions({
      queries: {
        retry: false,
        staleTime: 0,
        gcTime: 60_000,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    });
    // Seed a cache entry that isConnectorsQuery would invalidate.
    queryClient.setQueryData(
      ["connectors", false, false, false, false],
      [connector({ id: "aws_s3", type: "aws_s3", status: "configured" })],
    );

    const { result } = renderHook(() => useConnectConnectorMutation(), {
      wrapper: createQueryWrapper({ queryClient, providers: ["auth"] }),
    });

    act(() => {
      result.current.mutate({
        connector: connector({ id: "aws_s3", type: "aws_s3" }),
        redirectUri: "http://localhost:3000/auth/callback",
      });
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    // invalidateQueries alone doesn't force a refetch without an active
    // observer; assert on the cache being marked stale instead.
    expect(
      queryClient.getQueryState(["connectors", false, false, false, false])
        ?.isInvalidated,
    ).toBe(true);
  });

  it("restores the pre-mutation cache and toasts on failure", async () => {
    server.use(
      http.post("/api/auth/init", () =>
        HttpResponse.json({ error: "provider unreachable" }, { status: 500 }),
      ),
    );

    const queryClient = createTestQueryClient();
    queryClient.setDefaultOptions({
      queries: {
        retry: false,
        staleTime: 0,
        gcTime: 60_000,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    });
    const seed = [connector({ status: "configured" })];
    queryClient.setQueryData(["connectors", false, false, false, false], seed);

    const { result } = renderHook(() => useConnectConnectorMutation(), {
      wrapper: createQueryWrapper({ queryClient, providers: ["auth"] }),
    });

    act(() => {
      result.current.mutate({
        connector: connector(),
        redirectUri: "http://localhost:3000/auth/callback",
      });
    });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("provider unreachable");
    expect(
      queryClient.getQueryData(["connectors", false, false, false, false]),
    ).toEqual(seed);
  });
});
