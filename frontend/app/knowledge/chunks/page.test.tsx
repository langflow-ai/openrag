/**
 * ChunksPage — tests for highlight wiring through the real component.
 *
 * Per AGENTS.md: mock the network, not the module. We drive
 * useFileScopedChunksQuery through MSW handlers so the URL params, request
 * payload, React Query wiring, and rendered output all stay under test.
 *
 * Geometry-dependent behaviour belongs in Playwright; jsdom has no layout engine.
 */

import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type { ChunkResult } from "@/app/api/queries/useGetSearchQuery";
import { authPresets } from "@/test-utils/fixtures/auth";
import { server } from "@/test-utils/msw/server";
import { renderWithProviders, waitFor } from "@/test-utils/render";
import { setMockLocation } from "@/test-utils/router";
import ProtectedChunksPage from "./page";

function chunk(overrides: Partial<ChunkResult> = {}): ChunkResult {
  return {
    filename: "test.pdf",
    mimetype: "application/pdf",
    page: 1,
    text: "The quick brown fox",
    score: 1,
    chunk_id: "c1",
    ...overrides,
  };
}

/** Install a /api/search handler and record every request body. */
function serveSearch(chunks: ChunkResult[]) {
  const calls: { query: string }[] = [];
  server.use(
    http.post("/api/search", async ({ request }) => {
      const body = (await request.json()) as { query: string };
      calls.push({ query: body.query });
      return HttpResponse.json({ results: chunks, warnings: [] });
    }),
  );
  return calls;
}

describe("ChunksPage — highlight wiring", () => {
  it("fires only the wildcard request when no ?q= param is present", async () => {
    setMockLocation({
      pathname: "/knowledge/chunks",
      searchParams: { filename: "test.pdf" },
    });
    const calls = serveSearch([chunk()]);

    renderWithProviders(<ProtectedChunksPage />, {
      providers: ["auth", "knowledgeFilter"],
      auth: authPresets.admin,
    });

    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(1));
    expect(calls.every((c) => c.query === "*")).toBe(true);
  });

  it("fires a second request with the search query when ?q= is present", async () => {
    setMockLocation({
      pathname: "/knowledge/chunks",
      searchParams: { filename: "test.pdf", q: "brown fox" },
    });
    const calls = serveSearch([
      chunk({ highlights: ["quick <mark>brown fox</mark>"] }),
    ]);

    renderWithProviders(<ProtectedChunksPage />, {
      providers: ["auth", "knowledgeFilter"],
      auth: authPresets.admin,
    });

    // Two requests: wildcard (all chunks) + the search query (highlights).
    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(2));
    expect(calls.some((c) => c.query === "*")).toBe(true);
    expect(calls.some((c) => c.query === "brown fox")).toBe(true);
  });

  it("renders all chunks even when only some match the search query", async () => {
    setMockLocation({
      pathname: "/knowledge/chunks",
      searchParams: { filename: "test.pdf", q: "fox" },
    });

    server.use(
      http.post("/api/search", async ({ request }) => {
        const body = (await request.json()) as { query: string };
        if (body.query === "*") {
          return HttpResponse.json({
            results: [
              chunk({ chunk_id: "c1", text: "The quick brown fox" }),
              chunk({ chunk_id: "c2", text: "Unrelated content here" }),
            ],
            warnings: [],
          });
        }
        return HttpResponse.json({
          results: [
            chunk({
              chunk_id: "c1",
              text: "The quick brown fox",
              highlights: ["quick <mark>fox</mark>"],
            }),
          ],
          warnings: [],
        });
      }),
    );

    renderWithProviders(<ProtectedChunksPage />, {
      providers: ["auth", "knowledgeFilter"],
      auth: authPresets.admin,
    });

    // Both chunks must appear — the non-matching one must not be dropped.
    await waitFor(() =>
      expect(screen.getByText("Chunk 1")).toBeInTheDocument(),
    );
    expect(screen.getByText("Chunk 2")).toBeInTheDocument();
  });

  it("renders highlighted mark elements for matching chunks", async () => {
    setMockLocation({
      pathname: "/knowledge/chunks",
      searchParams: { filename: "test.pdf", q: "fox" },
    });

    server.use(
      http.post("/api/search", async ({ request }) => {
        const body = (await request.json()) as { query: string };
        if (body.query === "*") {
          return HttpResponse.json({
            results: [chunk({ chunk_id: "c1", text: "The quick brown fox" })],
            warnings: [],
          });
        }
        return HttpResponse.json({
          results: [
            chunk({
              chunk_id: "c1",
              text: "The quick brown fox",
              highlights: ["The quick brown <mark>fox</mark>"],
            }),
          ],
          warnings: [],
        });
      }),
    );

    const { container } = renderWithProviders(<ProtectedChunksPage />, {
      providers: "all",
      auth: authPresets.admin,
    });

    await waitFor(() =>
      expect(container.querySelector("mark")).toBeInTheDocument(),
    );
    expect(container.querySelector("mark")?.textContent).toBe("fox");
  });
});
