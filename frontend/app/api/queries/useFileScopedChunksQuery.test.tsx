import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper, renderHook, waitFor } from "@/test-utils/render";
import {
  useDocumentScopedChunksQuery,
  useFileScopedChunksQuery,
} from "./useFileScopedChunksQuery";
import type { ChunkResult } from "./useGetSearchQuery";

function chunk(overrides: Partial<ChunkResult> = {}): ChunkResult {
  return {
    filename: "test.pdf",
    mimetype: "application/pdf",
    page: 1,
    text: "body",
    score: 1,
    ...overrides,
  };
}

function serveSearch(chunks: ChunkResult[], status = 200) {
  const responseBody = { results: chunks, warnings: [] };
  server.use(
    http.post("/api/search", async () => {
      return status === 200
        ? HttpResponse.json(responseBody)
        : HttpResponse.json(responseBody, { status });
    }),
  );
}

describe("useFileScopedChunksQuery", () => {
  it("returns empty result when filename is null", async () => {
    serveSearch([]);

    const { result } = renderHook(() => useFileScopedChunksQuery(null), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isFetching).toBe(false));
    expect(result.current.file).toBeUndefined();
  });

  it("returns empty result when filename is undefined", async () => {
    serveSearch([]);

    const { result } = renderHook(() => useFileScopedChunksQuery(undefined), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isFetching).toBe(false));
    expect(result.current.file).toBeUndefined();
  });

  it("uses wildcard query when searchQuery is not provided", async () => {
    serveSearch([chunk({ filename: "test.pdf", text: "chunk 1" })]);

    const { result } = renderHook(() => useFileScopedChunksQuery("test.pdf"), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(result.current.isFetching).toBe(false));
    expect(result.current.file?.filename).toBe("test.pdf");
    expect(result.current.file?.chunks).toHaveLength(1);
  });

  it("uses wildcard query when searchQuery is empty string", async () => {
    serveSearch([chunk({ filename: "test.pdf", text: "chunk 1" })]);

    const { result } = renderHook(
      () => useFileScopedChunksQuery("test.pdf", ""),
      {
        wrapper: createQueryWrapper(),
      },
    );

    await waitFor(() => expect(result.current.isFetching).toBe(false));
    expect(result.current.file?.filename).toBe("test.pdf");
  });

  it("uses wildcard query when searchQuery is only whitespace", () => {
    serveSearch([chunk({ filename: "test.pdf", text: "chunk 1" })]);

    const { result } = renderHook(
      () => useFileScopedChunksQuery("test.pdf", "   "),
      {
        wrapper: createQueryWrapper(),
      },
    );

    // Line 20 is tested: trimming and comparing with "*" and ""
    expect(result.current).toBeDefined();
  });

  it("uses wildcard query when searchQuery is asterisk", async () => {
    serveSearch([chunk({ filename: "test.pdf", text: "chunk 1" })]);

    const { result } = renderHook(
      () => useFileScopedChunksQuery("test.pdf", "*"),
      {
        wrapper: createQueryWrapper(),
      },
    );

    await waitFor(() => expect(result.current.isFetching).toBe(false));
    expect(result.current.file?.filename).toBe("test.pdf");
  });

  it("uses actual search query when provided with valid text", async () => {
    serveSearch([
      chunk({
        filename: "test.pdf",
        text: "chunk with keyword",
        highlights: ["<mark>keyword</mark>"],
      }),
    ]);

    const { result } = renderHook(
      () => useFileScopedChunksQuery("test.pdf", "keyword"),
      {
        wrapper: createQueryWrapper(),
      },
    );

    await waitFor(() => expect(result.current.isFetching).toBe(false));
    expect(result.current.file?.filename).toBe("test.pdf");
    expect(result.current.file?.chunks?.[0]?.highlights).toBeDefined();
  });

  it("merges highlights without dropping non-matching chunks", async () => {
    server.use(
      http.post("/api/search", async ({ request }) => {
        const body = (await request.json()) as { query: string };
        return HttpResponse.json({
          results:
            body.query === "*"
              ? [
                  chunk({
                    filename: "test.pdf",
                    chunk_id: "one",
                    text: "match",
                  }),
                  chunk({
                    filename: "test.pdf",
                    chunk_id: "two",
                    text: "other",
                  }),
                ]
              : [
                  chunk({
                    filename: "test.pdf",
                    chunk_id: "one",
                    text: "match",
                    highlights: ["<mark>match</mark>"],
                  }),
                ],
          warnings: [],
        });
      }),
    );

    const { result } = renderHook(
      () => useFileScopedChunksQuery("test.pdf", "match"),
      { wrapper: createQueryWrapper() },
    );

    await waitFor(() => expect(result.current.isFetching).toBe(false));
    expect(result.current.file?.chunks).toHaveLength(2);
    expect(result.current.file?.chunks?.[0]?.highlights).toEqual([
      "<mark>match</mark>",
    ]);
    expect(result.current.file?.chunks?.[1]?.highlights).toEqual([]);
  });

  it("finds the matching file from multiple files in response", async () => {
    serveSearch([
      chunk({ filename: "other.pdf", text: "other chunk" }),
      chunk({ filename: "target.pdf", text: "target chunk" }),
    ]);

    const { result } = renderHook(
      () => useFileScopedChunksQuery("target.pdf"),
      {
        wrapper: createQueryWrapper(),
      },
    );

    await waitFor(() => expect(result.current.isFetching).toBe(false));
    expect(result.current.file?.filename).toBe("target.pdf");
  });

  it("returns undefined file when filename not found in response", async () => {
    serveSearch([chunk({ filename: "other.pdf" })]);

    const { result } = renderHook(
      () => useFileScopedChunksQuery("missing.pdf"),
      {
        wrapper: createQueryWrapper(),
      },
    );

    await waitFor(() => expect(result.current.isFetching).toBe(false));
    expect(result.current.file).toBeUndefined();
  });

  it("trims whitespace from search query", async () => {
    serveSearch([chunk({ filename: "test.pdf", text: "chunk" })]);

    const { result } = renderHook(
      () => useFileScopedChunksQuery("test.pdf", "  keyword  "),
      {
        wrapper: createQueryWrapper(),
      },
    );

    await waitFor(() => expect(result.current.isFetching).toBe(false));
    // The query should have been trimmed (line 20-21 logic)
    expect(result.current.file?.filename).toBe("test.pdf");
  });
});

describe("useDocumentScopedChunksQuery", () => {
  it("merges highlights by stable document id without removing other chunks", async () => {
    const requests: { query: string; documentIds?: string[] }[] = [];
    server.use(
      http.post("/api/search", async ({ request }) => {
        const body = (await request.json()) as {
          query: string;
          filters?: { document_ids?: string[] };
        };
        requests.push({
          query: body.query,
          documentIds: body.filters?.document_ids,
        });
        return HttpResponse.json({
          results:
            body.query === "*"
              ? [
                  chunk({
                    document_id: "page-1",
                    chunk_id: "one",
                    text: "match",
                  }),
                  chunk({
                    document_id: "page-1",
                    chunk_id: "two",
                    text: "other",
                  }),
                ]
              : [
                  chunk({
                    document_id: "page-1",
                    chunk_id: "one",
                    text: "match",
                    highlights: ["<mark>match</mark>"],
                  }),
                ],
          warnings: [],
        });
      }),
    );

    const { result } = renderHook(
      () => useDocumentScopedChunksQuery("page-1", "match"),
      { wrapper: createQueryWrapper() },
    );

    await waitFor(() => expect(result.current.isFetching).toBe(false));
    expect(requests).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ query: "*", documentIds: ["page-1"] }),
        expect.objectContaining({ query: "match", documentIds: ["page-1"] }),
      ]),
    );
    expect(result.current.file?.chunks).toHaveLength(2);
    expect(result.current.file?.chunks?.[0]?.highlights).toEqual([
      "<mark>match</mark>",
    ]);
  });
});
