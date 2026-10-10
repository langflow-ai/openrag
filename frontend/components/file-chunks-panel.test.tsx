/**
 * FileChunksPanel — MSW-based tests for highlight wiring.
 *
 * Per AGENTS.md: mock the network, not the module. Tests drive
 * useFileScopedChunksQuery through /api/search handlers so the searchQuery
 * prop, request payloads, merge logic, and rendered output all stay under test.
 */

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type { ChunkResult } from "@/app/api/queries/useGetSearchQuery";
import { authPresets } from "@/test-utils/fixtures/auth";
import { server } from "@/test-utils/msw/server";
import {
  createTestQueryClient,
  renderWithProviders,
  waitFor,
} from "@/test-utils/render";
import { FileChunksPanel } from "./file-chunks-panel";

/**
 * Seed the query client with a global search result so useFileScopedChunksQuery
 * can find globally-normalised scores via getQueriesData(["search"]).
 * The key must be a real (non-wildcard, non-file-scoped) search entry.
 */
function seedGlobalSearch(
  queryClient: ReturnType<typeof createTestQueryClient>,
  query: string,
  chunks: ChunkResult[],
) {
  // Compute global min-max normalisation the same way useGetSearchQuery does.
  const scores = chunks.map((c) => c.score ?? 0);
  const globalMin = Math.min(...scores);
  const globalMax = Math.max(...scores);
  const spread = globalMax - globalMin;
  const normalise = (raw: number) =>
    spread > 0 ? (raw - globalMin) / spread : raw > 0 ? 1 : 0;

  const chunksWithNorm = chunks.map((c) => ({
    ...c,
    normalizedScore: normalise(c.score ?? 0),
  }));

  const data = {
    files: [
      {
        filename: "doc.pdf",
        mimetype: "application/pdf",
        chunkCount: chunksWithNorm.length,
        maxScore: Math.max(
          ...chunksWithNorm.map((c) => c.normalizedScore ?? 0),
        ),
        relevanceTier: "high",
        isSemanticMatch: chunksWithNorm.every(
          (c) => !c.highlights?.some((h) => h.includes("<mark>")),
        ),
        chunkTiers: { high: 0, medium: 0, low: 0 },
        source_url: "",
        size: 0,
        connector_type: "local",
        chunks: chunksWithNorm,
      },
    ],
    warnings: [],
  };

  // setQueryDefaults must be called BEFORE setQueryData so the entry is
  // created with gcTime:Infinity from the start — with gcTime:0 (the test
  // default) the entry would be GC'd on the next microtask tick, before the
  // component mounts its observer.
  queryClient.setQueryDefaults(["search", null, query], { gcTime: Infinity });
  queryClient.setQueryData(["search", null, query], data);
}

function chunk(overrides: Partial<ChunkResult> = {}): ChunkResult {
  return {
    filename: "doc.pdf",
    mimetype: "application/pdf",
    page: 1,
    text: "The quick brown fox",
    score: 1,
    chunk_id: "c1",
    ...overrides,
  };
}

describe("FileChunksPanel — highlight wiring", () => {
  it("shows all chunks when no searchQuery is provided", async () => {
    server.use(
      http.post("/api/search", () =>
        HttpResponse.json({
          results: [
            chunk({ chunk_id: "c1", text: "First chunk content" }),
            chunk({ chunk_id: "c2", text: "Second chunk content" }),
          ],
          warnings: [],
        }),
      ),
    );

    renderWithProviders(<FileChunksPanel filename="doc.pdf" />, {
      providers: ["auth", "knowledgeFilter"],
      auth: authPresets.admin,
    });

    await waitFor(() =>
      expect(screen.getByText("First chunk content")).toBeInTheDocument(),
    );
    expect(screen.getByText("Second chunk content")).toBeInTheDocument();
  });

  it("passes searchQuery to the search API and merges highlights", async () => {
    const calls: { query: string }[] = [];
    const searchChunk = chunk({
      chunk_id: "c1",
      text: "The quick brown fox",
      score: 1.0,
      highlights: ["The quick <mark>fox</mark>"],
    });
    const qc = createTestQueryClient();
    seedGlobalSearch(qc, "fox", [searchChunk]);

    server.use(
      http.post("/api/search", async ({ request }) => {
        const body = (await request.json()) as { query: string };
        calls.push({ query: body.query });
        if (body.query === "*") {
          return HttpResponse.json({
            results: [chunk({ chunk_id: "c1", text: "The quick brown fox" })],
            warnings: [],
          });
        }
        return HttpResponse.json({ results: [searchChunk], warnings: [] });
      }),
    );

    const { container } = renderWithProviders(
      <FileChunksPanel filename="doc.pdf" searchQuery="fox" />,
      { providers: ["auth", "knowledgeFilter"], queryClient: qc },
    );

    // Both a wildcard and a highlight request must have been sent.
    await waitFor(() => expect(calls.length).toBeGreaterThanOrEqual(2));
    expect(calls.some((c) => c.query === "*")).toBe(true);
    expect(calls.some((c) => c.query === "fox")).toBe(true);

    // The <mark> element must be visible in the rendered output.
    await waitFor(() =>
      expect(container.querySelector("mark")).toBeInTheDocument(),
    );
    expect(container.querySelector("mark")?.textContent).toBe("fox");
  });

  it("only shows chunks returned by the search when a searchQuery is provided", async () => {
    // c1 is returned by the global search (scored). c2 is NOT in the global search.
    // The panel must only show c1.
    const c1 = chunk({
      chunk_id: "c1",
      text: "Matching content fox",
      score: 1.0,
      highlights: ["Matching <mark>fox</mark>"],
    });
    const qc = createTestQueryClient();
    seedGlobalSearch(qc, "fox", [c1]);

    server.use(
      http.post("/api/search", async ({ request }) => {
        const body = (await request.json()) as { query: string };
        if (body.query === "*") {
          return HttpResponse.json({
            results: [
              chunk({ chunk_id: "c1", text: "Matching content fox" }),
              chunk({ chunk_id: "c2", text: "Unrelated content here" }),
            ],
            warnings: [],
          });
        }
        return HttpResponse.json({ results: [c1], warnings: [] });
      }),
    );

    const { container } = renderWithProviders(
      <FileChunksPanel filename="doc.pdf" searchQuery="fox" />,
      { providers: ["auth", "knowledgeFilter"], queryClient: qc },
    );

    // c1 must be visible with its highlight mark.
    await waitFor(() =>
      expect(container.querySelector("mark")).toBeInTheDocument(),
    );
    expect(container.querySelector("mark")?.textContent).toBe("fox");

    // c2 was not returned by the global search — it must not appear.
    expect(
      screen.queryByText("Unrelated content here"),
    ).not.toBeInTheDocument();
  });
});

describe("FileChunksPanel — hideIrrelevant", () => {
  it("hides low-relevance chunks and shows a banner when hideIrrelevant is true", async () => {
    // c1 has a high score (1.0), c2 has a low score (0.1).
    // After global min-max: c1 → 1.0 (high tier), c2 → 0.0 (low tier, hidden).
    const c1 = chunk({
      chunk_id: "c1",
      text: "Highly relevant content",
      score: 1.0,
    });
    const c2 = chunk({
      chunk_id: "c2",
      text: "Totally irrelevant stuff",
      score: 0.1,
    });
    const qc = createTestQueryClient();
    seedGlobalSearch(qc, "relevant", [c1, c2]);

    server.use(
      http.post("/api/search", async ({ request }) => {
        const body = (await request.json()) as { query: string };
        if (body.query === "*") {
          return HttpResponse.json({ results: [c1, c2], warnings: [] });
        }
        return HttpResponse.json({ results: [c1, c2], warnings: [] });
      }),
    );

    renderWithProviders(
      <FileChunksPanel
        filename="doc.pdf"
        searchQuery="relevant"
        hideIrrelevant
      />,
      {
        providers: ["auth", "knowledgeFilter"],
        auth: authPresets.admin,
        queryClient: qc,
      },
    );

    // The high-relevance chunk must be visible.
    await waitFor(() =>
      expect(screen.getByText("Highly relevant content")).toBeInTheDocument(),
    );

    // The low-relevance chunk must be hidden.
    expect(
      screen.queryByText("Totally irrelevant stuff"),
    ).not.toBeInTheDocument();

    // The banner must announce how many chunks are hidden.
    expect(
      screen.getByText(/1 low-relevance chunk hidden/i),
    ).toBeInTheDocument();
  });

  it("reveals hidden chunks when the user clicks Show all", async () => {
    const c1 = chunk({
      chunk_id: "c1",
      text: "Highly relevant content",
      score: 1.0,
    });
    const c2 = chunk({
      chunk_id: "c2",
      text: "Totally irrelevant stuff",
      score: 0.1,
    });
    const qc = createTestQueryClient();
    seedGlobalSearch(qc, "relevant", [c1, c2]);

    server.use(
      http.post("/api/search", async ({ request }) => {
        const body = (await request.json()) as { query: string };
        if (body.query === "*") {
          return HttpResponse.json({ results: [c1, c2], warnings: [] });
        }
        return HttpResponse.json({ results: [c1, c2], warnings: [] });
      }),
    );

    const user = userEvent.setup();

    renderWithProviders(
      <FileChunksPanel
        filename="doc.pdf"
        searchQuery="relevant"
        hideIrrelevant
      />,
      {
        providers: ["auth", "knowledgeFilter"],
        auth: authPresets.admin,
        queryClient: qc,
      },
    );

    // Wait for the banner to appear, then click anywhere on it (entire banner is a button).
    const banner = await screen.findByRole("button", { name: /show all/i });
    await user.click(banner);

    // Now the low-relevance chunk must be visible.
    await waitFor(() =>
      expect(screen.getByText("Totally irrelevant stuff")).toBeInTheDocument(),
    );

    // The banner should now offer "Hide low-relevance".
    expect(
      screen.getByText(/showing all chunks including low-relevance/i),
    ).toBeInTheDocument();
  });

  it("retains semantically relevant chunks without keyword matches and shows the 'Semantically relevant' badge", async () => {
    // c1 is a semantic match — high score, no highlights (pure KNN hit).
    // c2 is not in the global search (score 0 after merge) — should not appear.
    const c1 = chunk({
      chunk_id: "c1",
      text: "Structured XML and JSON format trees for document extraction",
      score: 2.8,
      highlights: [],
    });
    const qc = createTestQueryClient();
    seedGlobalSearch(qc, "parsing tool", [c1]);

    server.use(
      http.post("/api/search", async ({ request }) => {
        const body = (await request.json()) as { query: string };
        if (body.query === "*") {
          return HttpResponse.json({
            results: [
              chunk({
                chunk_id: "c1",
                text: "Structured XML and JSON format trees for document extraction",
                score: 1.0,
              }),
              chunk({
                chunk_id: "c2",
                text: "Quantum computing qubits and superposition",
                score: 0.0,
              }),
            ],
            warnings: [],
          });
        }
        return HttpResponse.json({ results: [c1], warnings: [] });
      }),
    );

    renderWithProviders(
      <FileChunksPanel
        filename="doc.pdf"
        searchQuery="parsing tool"
        hideIrrelevant
      />,
      {
        providers: ["auth", "knowledgeFilter"],
        auth: authPresets.admin,
        queryClient: qc,
      },
    );

    // The semantically relevant chunk must be displayed even with no keyword marks.
    await waitFor(() =>
      expect(
        screen.getByText(
          "Structured XML and JSON format trees for document extraction",
        ),
      ).toBeInTheDocument(),
    );

    // Badge must say "Semantically relevant (100%)" — 100% because it's the only scored chunk.
    expect(
      screen.getByText("Semantically relevant (100%)"),
    ).toBeInTheDocument();
    expect(screen.queryByText("100% relevance")).not.toBeInTheDocument();

    // c2 was not in the global search — must not appear.
    expect(
      screen.queryByText("Quantum computing qubits and superposition"),
    ).not.toBeInTheDocument();
  });
});
