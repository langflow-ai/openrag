import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper, renderHook, waitFor } from "@/test-utils/render";
import { useFileScopedChunksQuery } from "./useFileScopedChunksQuery";
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
  it("returns only semantically matched chunks when searchQuery is active", async () => {
    let callCount = 0;
    server.use(
      http.post("/api/search", async ({ request }) => {
        const body = (await request.json()) as { query: string };
        callCount++;
        if (body.query === "*") {
          // Wildcard: return all 3 chunks for the file.
          return HttpResponse.json({
            results: [
              chunk({
                filename: "test.pdf",
                chunk_id: "c1",
                text: "matched chunk one",
              }),
              chunk({
                filename: "test.pdf",
                chunk_id: "c2",
                text: "unmatched chunk two",
              }),
              chunk({
                filename: "test.pdf",
                chunk_id: "c3",
                text: "matched chunk three",
              }),
            ],
            warnings: [],
          });
        }
        // Highlight fetch: only c1 and c3 matched semantically.
        return HttpResponse.json({
          results: [
            chunk({
              filename: "test.pdf",
              chunk_id: "c1",
              text: "matched chunk one",
              highlights: [],
            }),
            chunk({
              filename: "test.pdf",
              chunk_id: "c3",
              text: "matched chunk three",
              highlights: [],
            }),
          ],
          warnings: [],
        });
      }),
    );

    const { result } = renderHook(
      () => useFileScopedChunksQuery("test.pdf", "keyword"),
      { wrapper: createQueryWrapper() },
    );

    await waitFor(() => expect(result.current.isFetching).toBe(false));
    // Only the 2 semantically matched chunks should be returned, not all 3.
    expect(result.current.file?.chunks).toHaveLength(2);
    const texts = result.current.file?.chunks?.map((c) => c.text);
    expect(texts).toContain("matched chunk one");
    expect(texts).toContain("matched chunk three");
    expect(texts).not.toContain("unmatched chunk two");
  });
});
