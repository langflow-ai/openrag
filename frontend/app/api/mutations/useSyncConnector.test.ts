/**
 * Tests for the four mutations in useSyncConnector.ts: syncing one connector
 * or all of them, and previewing either sync before it runs.
 */
import { act, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper } from "@/test-utils/render";
import {
  useSyncAllConnectors,
  useSyncAllConnectorsPreview,
  useSyncConnector,
  useSyncConnectorPreview,
} from "./useSyncConnector";

describe("useSyncAllConnectors", () => {
  it("posts to /api/connectors/sync-all and resolves with the response", async () => {
    server.use(
      http.post("/api/connectors/sync-all", () =>
        HttpResponse.json({ status: "ok", message: "synced" }),
      ),
    );

    const { result } = renderHook(() => useSyncAllConnectors(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.message).toBe("synced");
  });

  it("throws the backend's error message when the response is not ok", async () => {
    server.use(
      http.post("/api/connectors/sync-all", () =>
        HttpResponse.json(
          { error: "no connectors configured" },
          { status: 500 },
        ),
      ),
    );

    const { result } = renderHook(() => useSyncAllConnectors(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate());

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("no connectors configured");
  });

  it("falls back to a default message when the error body has no error field", async () => {
    server.use(
      http.post("/api/connectors/sync-all", () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useSyncAllConnectors(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate());

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Failed to sync connectors");
  });
});

describe("useSyncConnector", () => {
  it("posts to /api/connectors/:type/sync with the request body", async () => {
    let capturedBody: unknown;
    server.use(
      http.post("/api/connectors/google_drive/sync", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({ status: "ok", message: "synced" });
      }),
    );

    const { result } = renderHook(() => useSyncConnector(), {
      wrapper: createQueryWrapper(),
    });

    act(() =>
      result.current.mutate({
        connectorType: "google_drive",
        body: { connection_id: "conn-1", max_files: 10 },
      }),
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedBody).toEqual({ connection_id: "conn-1", max_files: 10 });
  });

  it("sends an empty object body when no body is given", async () => {
    let capturedBody: unknown;
    server.use(
      http.post("/api/connectors/aws_s3/sync", async ({ request }) => {
        capturedBody = await request.json();
        return HttpResponse.json({ status: "ok", message: "synced" });
      }),
    );

    const { result } = renderHook(() => useSyncConnector(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate({ connectorType: "aws_s3" }));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(capturedBody).toEqual({});
  });

  it("throws a connector-specific default message on failure", async () => {
    server.use(
      http.post("/api/connectors/onedrive/sync", () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useSyncConnector(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate({ connectorType: "onedrive" }));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Failed to sync onedrive");
  });
});

describe("useSyncConnectorPreview", () => {
  it("posts to /api/connectors/:type/sync-preview and resolves the preview", async () => {
    server.use(
      http.post("/api/connectors/google_drive/sync-preview", () =>
        HttpResponse.json({
          connector_type: "google_drive",
          synced_count: 3,
          orphans: [{ document_id: "d1", filename: "old.pdf" }],
          orphans_available: true,
          updates: [],
          updates_available: true,
        }),
      ),
    );

    const { result } = renderHook(() => useSyncConnectorPreview(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate("google_drive"));

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.orphans).toHaveLength(1);
    expect(result.current.data?.orphans_available).toBe(true);
  });

  it("throws with a connector-specific message when the preview fails", async () => {
    server.use(
      http.post("/api/connectors/google_drive/sync-preview", () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useSyncConnectorPreview(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate("google_drive"));

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe(
      "Failed to preview sync for google_drive",
    );
  });
});

describe("useSyncAllConnectorsPreview", () => {
  it("posts to /api/connectors/sync-all-preview and resolves the aggregate preview", async () => {
    server.use(
      http.post("/api/connectors/sync-all-preview", () =>
        HttpResponse.json({
          orphans_by_type: { google_drive: [] },
          synced_count_by_type: { google_drive: 5 },
          orphans_available_by_type: { google_drive: true },
          updates_by_type: { google_drive: [] },
          updates_available_by_type: { google_drive: true },
        }),
      ),
    );

    const { result } = renderHook(() => useSyncAllConnectorsPreview(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate());

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.synced_count_by_type.google_drive).toBe(5);
  });

  it("throws a default message when the response has no error field", async () => {
    server.use(
      http.post("/api/connectors/sync-all-preview", () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );

    const { result } = renderHook(() => useSyncAllConnectorsPreview(), {
      wrapper: createQueryWrapper(),
    });

    act(() => result.current.mutate());

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(result.current.error?.message).toBe("Failed to preview sync");
  });
});
