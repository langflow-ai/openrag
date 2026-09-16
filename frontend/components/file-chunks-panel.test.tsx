/**
 * FileChunksPanel — MSW-based tests for highlight wiring.
 *
 * Per AGENTS.md: mock the network, not the module. Tests drive
 * useFileScopedChunksQuery through /api/search handlers so the searchQuery
 * prop, request payloads, merge logic, and rendered output all stay under test.
 */

import { screen } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type { ChunkResult } from "@/app/api/queries/useGetSearchQuery";
import { authPresets } from "@/test-utils/fixtures/auth";
import { server } from "@/test-utils/msw/server";
import { renderWithProviders, waitFor } from "@/test-utils/render";
import { FileChunksPanel } from "./file-chunks-panel";

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
        return HttpResponse.json({
          results: [
            chunk({
              chunk_id: "c1",
              text: "The quick brown fox",
              highlights: ["The quick <mark>fox</mark>"],
            }),
          ],
          warnings: [],
        });
      }),
    );

    const { container } = renderWithProviders(
      <FileChunksPanel filename="doc.pdf" searchQuery="fox" />,
      { providers: ["auth", "knowledgeFilter"] },
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

  it("preserves non-matching chunks when a searchQuery is provided", async () => {
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
        return HttpResponse.json({
          results: [
            chunk({
              chunk_id: "c1",
              text: "Matching content fox",
              highlights: ["Matching <mark>fox</mark>"],
            }),
          ],
          warnings: [],
        });
      }),
    );

    const { container } = renderWithProviders(
      <FileChunksPanel filename="doc.pdf" searchQuery="fox" />,
      { providers: ["auth", "knowledgeFilter"] },
    );

    // Both chunks must appear — the panel must not drop non-matching chunks.
    // Chunk 1 has highlights so we check for the text content (mark tag splits it)
    await waitFor(() =>
      expect(
        screen.getByText((content, element) => {
          return (
            element?.textContent === "Matching content fox" ||
            content.includes("Matching")
          );
        }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByText("Unrelated content here")).toBeInTheDocument();
    // Verify the highlight mark is rendered
    expect(container.querySelector("mark")?.textContent).toBe("fox");
  });
});
