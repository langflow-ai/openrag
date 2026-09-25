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

  it("fires both wildcard and search requests when only some chunks match the search query", async () => {
    setMockLocation({
      pathname: "/knowledge/chunks",
      searchParams: { filename: "test.pdf", q: "fox" },
    });

    const queriesSeen: string[] = [];
    server.use(
      http.post("/api/search", async ({ request }) => {
        const body = (await request.json()) as { query: string };
        queriesSeen.push(body.query);
        if (body.query === "*") {
          return HttpResponse.json({
            results: [
              chunk({ chunk_id: "c1", text: "The quick brown fox" }),
              chunk({ chunk_id: "c2", text: "Unrelated content here" }),
            ],
            warnings: [],
          });
        }
        // Only c1 matches the search query — c2 must still survive in the merged result.
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

    // Two requests must be fired: wildcard (full chunk list) + "fox" (highlights only).
    await waitFor(() => expect(queriesSeen.length).toBeGreaterThanOrEqual(2));
    expect(queriesSeen).toContain("*");
    expect(queriesSeen).toContain("fox");
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
      providers: ["auth", "knowledgeFilter"],
      auth: authPresets.admin,
    });

    await waitFor(() =>
      expect(container.querySelector("mark")).toBeInTheDocument(),
    );
    expect(container.querySelector("mark")?.textContent).toBe("fox");
  });
});

/**
 * Serve a minimal /api/search response carrying per-chunk access-control
 * fields. The query aggregates these onto the File object, making them visible
 * in the detail panel when chunkCount > 0.
 */
function serveFile(chunkOverrides: Partial<ChunkResult>) {
  const baseChunk: ChunkResult = {
    filename: "access-test.pdf",
    mimetype: "application/pdf",
    page: 1,
    text: "Sample content",
    score: 1,
    chunk_id: "c1",
  };
  server.use(
    http.post("/api/search", () =>
      HttpResponse.json({
        results: [{ ...baseChunk, ...chunkOverrides }],
        warnings: [],
      }),
    ),
  );
}

describe("ChunksPage — access-control sections", () => {
  it("renders every allowed_users entry (line 224)", async () => {
    setMockLocation({
      pathname: "/knowledge/chunks",
      searchParams: { filename: "access-test.pdf" },
    });
    serveFile({
      allowed_users: ["alice@example.com", "bob@example.com"],
      filename: "access-test.pdf",
    });

    renderWithProviders(<ProtectedChunksPage />, {
      providers: ["tooltip", "auth", "knowledgeFilter"],
      auth: authPresets.admin,
    });

    await screen.findByText("alice@example.com", {}, { timeout: 5000 });
    expect(screen.getByText("bob@example.com")).toBeTruthy();
    expect(screen.getByText("Allowed users")).toBeTruthy();
  });

  it("renders every allowed_groups entry (line 256)", async () => {
    setMockLocation({
      pathname: "/knowledge/chunks",
      searchParams: { filename: "access-test.pdf" },
    });
    serveFile({
      allowed_groups: ["admins", "editors"],
      filename: "access-test.pdf",
    });

    renderWithProviders(<ProtectedChunksPage />, {
      providers: ["tooltip", "auth", "knowledgeFilter"],
      auth: authPresets.admin,
    });

    await screen.findByText("admins", {}, { timeout: 5000 });
    expect(screen.getByText("editors")).toBeTruthy();
    expect(screen.getByText("Allowed groups")).toBeTruthy();
  });
});
