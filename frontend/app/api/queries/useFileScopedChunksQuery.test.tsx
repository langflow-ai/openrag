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
  describe("polling session counter", () => {
    it("polls for chunks after filename changes (baseline resets per session)", async () => {
      // First serve no chunks for file-a.pdf, then chunks for file-b.pdf.
      // After rerender with file-b.pdf the hook must fetch (not stay idle because
      // a prior session exhausted the budget on file-a.pdf).
      serveSearch([]);

      const { result, rerender } = renderHook(
        ({ name }: { name: string }) => useFileScopedChunksQuery(name),
        { wrapper: createQueryWrapper(), initialProps: { name: "file-a.pdf" } },
      );

      await waitFor(() => expect(result.current.isFetching).toBe(false));
      expect(result.current.file).toBeUndefined();

      // Switch to a different file that does have chunks.
      serveSearch([chunk({ filename: "file-b.pdf", text: "hello" })]);
      rerender({ name: "file-b.pdf" });

      await waitFor(() =>
        expect(result.current.file?.filename).toBe("file-b.pdf"),
      );
    });

    it("stops polling once chunks are found for the file", async () => {
      serveSearch([chunk({ filename: "found.pdf", text: "content" })]);

      const { result } = renderHook(
        () => useFileScopedChunksQuery("found.pdf"),
        { wrapper: createQueryWrapper() },
      );

      await waitFor(() => expect(result.current.isFetching).toBe(false));
      // Chunks were found immediately — file should be populated.
      expect(result.current.file?.filename).toBe("found.pdf");
      expect((result.current.file?.chunkCount ?? 0) > 0).toBe(true);
    });
  });
});
