/**
 * Tests for useListFiles.
 *
 * Verifies URL parameter serialization (including the new createdAfter /
 * createdBefore date-range params), response parsing, and error handling.
 */
import { renderHook, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper } from "@/test-utils/render";
import { useListFiles } from "./useListFiles";

function makeFileResponse(overrides: Record<string, unknown> = {}) {
  return {
    files: [],
    total: 0,
    is_approximate: false,
    page: 1,
    page_size: 25,
    after_key: null,
    ...overrides,
  };
}

describe("useListFiles", () => {
  it("sends created_after param when createdAfter is provided", async () => {
    let capturedUrl: string | undefined;
    server.use(
      http.get("/api/files", ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json(makeFileResponse());
      }),
    );

    const { result } = renderHook(
      () =>
        useListFiles({
          createdAfter: "2024-01-01T00:00:00.000Z",
        }),
      { wrapper: createQueryWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(capturedUrl!);
    expect(url.searchParams.get("created_after")).toBe(
      "2024-01-01T00:00:00.000Z",
    );
  });

  it("sends created_before param when createdBefore is provided", async () => {
    let capturedUrl: string | undefined;
    server.use(
      http.get("/api/files", ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json(makeFileResponse());
      }),
    );

    const { result } = renderHook(
      () =>
        useListFiles({
          createdBefore: "2024-01-31T23:59:59.999Z",
        }),
      { wrapper: createQueryWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(capturedUrl!);
    expect(url.searchParams.get("created_before")).toBe(
      "2024-01-31T23:59:59.999Z",
    );
  });

  it("sends both date params together", async () => {
    let capturedUrl: string | undefined;
    server.use(
      http.get("/api/files", ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json(makeFileResponse());
      }),
    );

    const { result } = renderHook(
      () =>
        useListFiles({
          createdAfter: "2024-03-01T00:00:00.000Z",
          createdBefore: "2024-03-31T23:59:59.999Z",
        }),
      { wrapper: createQueryWrapper() },
    );

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(capturedUrl!);
    expect(url.searchParams.get("created_after")).toBe(
      "2024-03-01T00:00:00.000Z",
    );
    expect(url.searchParams.get("created_before")).toBe(
      "2024-03-31T23:59:59.999Z",
    );
  });

  it("omits date params when not provided", async () => {
    let capturedUrl: string | undefined;
    server.use(
      http.get("/api/files", ({ request }) => {
        capturedUrl = request.url;
        return HttpResponse.json(makeFileResponse());
      }),
    );

    const { result } = renderHook(() => useListFiles({}), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const url = new URL(capturedUrl!);
    expect(url.searchParams.has("created_after")).toBe(false);
    expect(url.searchParams.has("created_before")).toBe(false);
  });

  it("maps indexed_time from the response", async () => {
    server.use(
      http.get("/api/files", () =>
        HttpResponse.json(
          makeFileResponse({
            files: [
              {
                filename: "doc.pdf",
                mimetype: "application/pdf",
                chunk_count: 5,
                source_url: "",
                owner: "user1",
                owner_name: "User One",
                owner_email: "user@example.com",
                file_size: 1024,
                connector_type: "local",
                allowed_users: [],
                allowed_groups: [],
                indexed_time: "2024-06-15T10:30:00.000Z",
              },
            ],
          }),
        ),
      ),
    );

    const { result } = renderHook(() => useListFiles({}), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    expect(result.current.data?.files[0]?.indexed_time).toBe(
      "2024-06-15T10:30:00.000Z",
    );
  });
});
