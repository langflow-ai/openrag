import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ParsedQueryData } from "@/contexts/knowledge-filter-context";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper, renderHook, waitFor } from "@/test-utils/render";
import {
  type ChunkResult,
  RELEVANCE_HIGH_THRESHOLD,
  RELEVANCE_MED_THRESHOLD,
  type SearchPayload,
  useGetSearchQuery,
} from "./useGetSearchQuery";

/**
 * Chosen by churn: 4 of this file's 18 commits in the last year were bug fixes
 * ("tune search relevance for partial and unique queries", "Knowledge search
 * fails with embedding model error" #1499, "display file names and fix
 * ingestion for onedrive" #1609, "bubble up search errors to ui").
 *
 * The request payload matters as much as the parsing here — several of those
 * fixes changed what gets SENT — so most tests capture the POST body.
 */

function chunk(overrides: Partial<ChunkResult> = {}): ChunkResult {
  return {
    filename: "a.pdf",
    mimetype: "application/pdf",
    page: 1,
    // Default text contains "term" so the literal-match gate passes for the
    // default runSearch("term") calls throughout the test suite.
    text: "term body",
    score: 1,
    ...overrides,
  };
}

function queryData(overrides: Partial<ParsedQueryData> = {}): ParsedQueryData {
  return {
    query: "",
    filters: {
      data_sources: [],
      document_types: [],
      owners: [],
      connector_types: [],
    },
    limit: 100,
    scoreThreshold: 1.25,
    color: "blue" as ParsedQueryData["color"],
    icon: "file" as ParsedQueryData["icon"],
    ...overrides,
  };
}

/** Serves /api/search and records the payload the hook sent. */
function serveSearch(body: Record<string, unknown>, status = 200) {
  const seen: { payload?: SearchPayload } = {};
  server.use(
    http.post("/api/search", async ({ request }) => {
      seen.payload = (await request.json()) as SearchPayload;
      return status === 200
        ? HttpResponse.json(body)
        : HttpResponse.json(body, { status });
    }),
  );
  return seen;
}

async function runSearch(query: string, data?: ParsedQueryData | null) {
  const rendered = renderHook(() => useGetSearchQuery(query, data), {
    wrapper: createQueryWrapper(),
  });
  await waitFor(() =>
    expect(
      rendered.result.current.isSuccess || rendered.result.current.isError,
    ).toBe(true),
  );
  return rendered;
}

beforeEach(() => {
  // getFiles console.errors before rethrowing; keep the test output clean.
  vi.spyOn(console, "error").mockImplementation(() => {});
});

describe("useGetSearchQuery", () => {
  describe("request payload", () => {
    it("defaults an empty query to the wildcard with a high limit", async () => {
      const seen = serveSearch({ results: [] });

      await runSearch("");

      // Regression: "update limits so knowledge filters file list isn't
      // limited to one" — wildcard must not use the 100 default.
      expect(seen.payload).toMatchObject({ query: "*", limit: 10000 });
    });

    it("uses queryData.query when the query argument is empty", async () => {
      const seen = serveSearch({ results: [] });

      await runSearch("", queryData({ query: "invoices" }));

      expect(seen.payload?.query).toBe("invoices");
      expect(seen.payload?.limit).toBe(100);
    });

    it("prefers the explicit query over queryData", async () => {
      const seen = serveSearch({ results: [] });

      await runSearch("explicit", queryData({ query: "ignored" }));

      expect(seen.payload?.query).toBe("explicit");
    });

    it("honours a custom limit from queryData", async () => {
      const seen = serveSearch({ results: [] });

      await runSearch("term", queryData({ limit: 7 }));

      expect(seen.payload?.limit).toBe(7);
    });

    it("caps the score threshold for short single-token queries", async () => {
      const seen = serveSearch({ results: [] });

      // Regression: "tune search relevance for partial and unique queries".
      await runSearch("acme", queryData({ scoreThreshold: 1.25 }));

      expect(seen.payload?.scoreThreshold).toBe(1.0);
    });

    it("leaves the threshold alone for longer or multi-word queries", async () => {
      const longQuery = serveSearch({ results: [] });
      await runSearch("quarterly", queryData({ scoreThreshold: 1.25 }));
      expect(longQuery.payload?.scoreThreshold).toBe(1.25);

      const multiWord = serveSearch({ results: [] });
      await runSearch("a b", queryData({ scoreThreshold: 1.25 }));
      expect(multiWord.payload?.scoreThreshold).toBe(1.25);
    });

    it("does not raise a threshold already below the cap", async () => {
      const seen = serveSearch({ results: [] });

      await runSearch("acme", queryData({ scoreThreshold: 0.4 }));

      expect(seen.payload?.scoreThreshold).toBe(0.4);
    });

    it("omits filters entirely when every dimension is empty", async () => {
      const seen = serveSearch({ results: [] });

      await runSearch("term", queryData());

      expect(seen.payload?.filters).toBeUndefined();
    });

    it("sends only the populated filter dimensions", async () => {
      const seen = serveSearch({ results: [] });

      await runSearch(
        "term",
        queryData({
          filters: {
            data_sources: ["s3"],
            document_types: [],
            owners: ["me@x.dev"],
            connector_types: [],
          },
        }),
      );

      expect(seen.payload?.filters).toEqual({
        data_sources: ["s3"],
        owners: ["me@x.dev"],
      });
    });

    it("treats a '*' dimension as unfiltered", async () => {
      const seen = serveSearch({ results: [] });

      await runSearch(
        "term",
        queryData({
          filters: {
            data_sources: ["*"],
            document_types: ["pdf"],
            owners: [],
            connector_types: [],
          },
        }),
      );

      expect(seen.payload?.filters).toEqual({ document_types: ["pdf"] });
    });
  });

  describe("grouping chunks into files", () => {
    // Pure min-max: norm(raw) = (raw - globalMin) / (globalMax - globalMin)
    // Zero-spread (all identical scores) → every chunk maps to 1.0
    function norm(raw: number, globalMin: number, globalMax: number) {
      const spread = globalMax - globalMin;
      return spread > 0 ? (raw - globalMin) / spread : 1;
    }

    it("groups chunks by filename and computes maxScore / relevanceTier / chunkTiers", async () => {
      // a.pdf: [4.0, 2.0]   b.pdf: [1.5]
      // globalMin=1.5, globalMax=4.0, spread=2.5
      // norm(4.0) = (4.0-1.5)/2.5 = 1.0  → High
      // norm(2.0) = (2.0-1.5)/2.5 = 0.2  → Low
      // norm(1.5) = (1.5-1.5)/2.5 = 0.0  → Low
      serveSearch({
        results: [
          chunk({ filename: "a.pdf", score: 4.0 }),
          chunk({ filename: "a.pdf", score: 2.0 }),
          chunk({ filename: "b.pdf", score: 1.5 }),
        ],
      });

      const { result } = await runSearch("term");

      const files = result.current.data?.files ?? [];
      expect(files).toHaveLength(2);

      const aPdf = files[0];
      expect(aPdf.filename).toBe("a.pdf");
      expect(aPdf.chunkCount).toBe(2);
      expect(aPdf.maxScore).toBeCloseTo(norm(4.0, 1.5, 4.0));
      expect(aPdf.relevanceTier).toBe("high");
      expect(aPdf.chunkTiers).toMatchObject({ high: 1, medium: 0, low: 1 });

      const bPdf = files[1];
      expect(bPdf.filename).toBe("b.pdf");
      expect(bPdf.maxScore).toBeCloseTo(norm(1.5, 1.5, 4.0));
      expect(bPdf.relevanceTier).toBe("low");
      expect(bPdf.chunkTiers).toMatchObject({ high: 0, medium: 0, low: 1 });
    });

    it("single result — maps to High (100%) via min-max", async () => {
      // Only one chunk: globalMin = globalMax → zero-spread → 1.0
      // This is correct: it IS the best (and only) match for this query.
      serveSearch({
        results: [chunk({ filename: "a.pdf", score: 1.26 })],
      });

      const { result } = await runSearch("term");

      const file = result.current.data?.files[0];
      expect(file?.maxScore).toBe(1.0);
      expect(file?.relevanceTier).toBe("high");
    });

    it("zero-spread — all identical scores map to High (100%)", async () => {
      // All chunks same score → spread = 0 → every chunk normalises to 1.0
      serveSearch({
        results: [
          chunk({ filename: "a.pdf", score: 3.5 }),
          chunk({ filename: "a.pdf", score: 3.5 }),
        ],
      });

      const { result } = await runSearch("term");

      const file = result.current.data?.files[0];
      expect(file?.maxScore).toBe(1.0);
      expect(file?.relevanceTier).toBe("high");
      expect(file?.chunkTiers).toMatchObject({ high: 2, medium: 0, low: 0 });
    });

    it("best chunk reaches High, worst reaches Low across files", async () => {
      // a.pdf has the global max, b.pdf has the global min
      // norm(4.0) = 1.0 → High;  norm(1.5) = 0.0 → Low
      serveSearch({
        results: [
          chunk({ filename: "a.pdf", score: 4.0 }),
          chunk({ filename: "b.pdf", score: 1.5 }),
        ],
      });

      const { result } = await runSearch("term");

      const files = result.current.data?.files ?? [];
      expect(files.find((f) => f.filename === "a.pdf")?.relevanceTier).toBe(
        "high",
      );
      expect(files.find((f) => f.filename === "b.pdf")?.relevanceTier).toBe(
        "low",
      );
    });

    it("exposes tier threshold constants", () => {
      expect(RELEVANCE_HIGH_THRESHOLD).toBeGreaterThan(RELEVANCE_MED_THRESHOLD);
      expect(RELEVANCE_HIGH_THRESHOLD).toBeLessThanOrEqual(1);
      expect(RELEVANCE_MED_THRESHOLD).toBeGreaterThanOrEqual(0);
    });
  });

  describe("literal-match gate", () => {
    it("returns empty when no chunk has highlights and no token appears in text", async () => {
      // Simulates "xylophone concerto" — pure KNN drift, no keyword match.
      serveSearch({
        results: [
          chunk({
            filename: "a.pdf",
            text: "quantum computing qubits",
            highlights: [],
          }),
        ],
      });

      const { result } = await runSearch("xylophone concerto");

      expect(result.current.data?.files).toHaveLength(0);
    });

    it("passes through when a token appears in chunk text", async () => {
      // The gate scans chunk text directly — highlights are not trusted because
      // OpenSearch fuzziness can produce false-positive highlight fragments.
      serveSearch({
        results: [
          chunk({
            filename: "a.pdf",
            text: "quantum computing qubits",
            highlights: [],
          }),
        ],
      });

      const { result } = await runSearch("quantum");

      expect(result.current.data?.files).toHaveLength(1);
    });

    it("passes through even when highlights contain a false-positive fuzzy match", async () => {
      // "concerto" → fuzzy → "convert" highlight is a false positive.
      // The gate ignores highlights and checks text directly.
      // "convert" IS in the text but "concerto" is NOT — gate fires.
      serveSearch({
        results: [
          chunk({
            filename: "a.pdf",
            text: "Solar cells convert sunlight into electricity",
            highlights: ["Solar cells <mark>convert</mark> sunlight"],
          }),
        ],
      });

      const { result } = await runSearch("xylophone concerto");

      expect(result.current.data?.files).toHaveLength(0);
    });

    it("passes through when a token appears in text with empty highlights", async () => {
      // Pure KNN hit — no keyword highlight — but word is literally in text.
      serveSearch({
        results: [
          chunk({
            filename: "a.pdf",
            text: "Apples are a type of fruit",
            highlights: [],
          }),
        ],
      });

      const { result } = await runSearch("apple");

      expect(result.current.data?.files).toHaveLength(1);
    });

    it("is case-insensitive in the text scan", async () => {
      serveSearch({
        results: [
          chunk({
            filename: "a.pdf",
            text: "QUANTUM COMPUTING",
            highlights: [],
          }),
        ],
      });

      const { result } = await runSearch("quantum");

      expect(result.current.data?.files).toHaveLength(1);
    });

    it("does not apply to wildcard queries", async () => {
      // Wildcard browse-all: no token check, everything passes through.
      serveSearch({
        results: [
          chunk({
            filename: "a.pdf",
            text: "something unrelated",
            highlights: [],
          }),
        ],
      });

      const { result } = await runSearch("*");

      expect(result.current.data?.files).toHaveLength(1);
    });

    it("stopword-only token 'your' does not pass the gate for 'your mom'", async () => {
      // "your" is a stopword — filtered out.
      // "mom" is meaningful but not in the text → gate fires.
      serveSearch({
        results: [
          chunk({
            filename: "a.pdf",
            text: "your quantum computing notes",
            highlights: [],
          }),
        ],
      });

      const { result } = await runSearch("your mom");

      expect(result.current.data?.files).toHaveLength(0);
    });

    it("meaningful token alongside stopword passes when meaningful token is in text", async () => {
      // "your" stripped, "quantum" kept → "quantum" IS in text → passes.
      serveSearch({
        results: [
          chunk({
            filename: "a.pdf",
            text: "your quantum computing notes",
            highlights: [],
          }),
        ],
      });

      const { result } = await runSearch("your quantum");

      expect(result.current.data?.files).toHaveLength(1);
    });

    it("all-stopword query falls back to full token list", async () => {
      // Every token is a stopword → fall back to checking all tokens.
      // "the" IS in the text → passes through (backend threshold decides).
      serveSearch({
        results: [
          chunk({
            filename: "a.pdf",
            text: "the quick brown fox",
            highlights: [],
          }),
        ],
      });

      const { result } = await runSearch("the a");

      expect(result.current.data?.files).toHaveLength(1);
    });

    it("filters out files without keyword matches while keeping matching files", async () => {
      // docling.pdf contains "docling", google_drive_doc.pdf does not.
      // The irrelevant file should be pruned so it doesn't appear or distort scoring.
      serveSearch({
        results: [
          chunk({
            filename: "docling.pdf",
            text: "docling parsing architecture and features",
            highlights: ["<mark>docling</mark> parsing architecture"],
            score: 3.5,
          }),
          chunk({
            filename: "google_drive_doc.pdf",
            text: "CS4750 Final Report Database Design",
            highlights: [],
            score: 2.0,
          }),
        ],
      });

      const { result } = await runSearch("docling");

      const files = result.current.data?.files ?? [];
      expect(files).toHaveLength(1);
      expect(files[0].filename).toBe("docling.pdf");
      expect(files[0].maxScore).toBe(1.0);
    });
  });

  describe("grouping chunks (continued)", () => {
    it("falls back to source_url, then to Untitled source (#1609)", async () => {
      serveSearch({
        results: [
          chunk({ filename: "  ", source_url: "https://x.dev/doc" }),
          chunk({ filename: "", source_url: "" }),
        ],
      });

      const { result } = await runSearch("term");

      expect(result.current.data?.files.map((f) => f.filename)).toEqual([
        "https://x.dev/doc",
        "Untitled source",
      ]);
    });

    it("backfills embedding metadata from a later chunk (#1499)", async () => {
      serveSearch({
        results: [
          chunk({ filename: "a.pdf" }),
          chunk({
            filename: "a.pdf",
            embedding_model: "granite",
            embedding_dimensions: 768,
          }),
        ],
      });

      const { result } = await runSearch("term");

      expect(result.current.data?.files[0]).toMatchObject({
        embedding_model: "granite",
        embedding_dimensions: 768,
      });
    });

    it("keeps the first chunk's embedding model once set (#1499)", async () => {
      serveSearch({
        results: [
          chunk({ filename: "a.pdf", embedding_model: "first" }),
          chunk({ filename: "a.pdf", embedding_model: "second" }),
        ],
      });

      const { result } = await runSearch("term");

      expect(result.current.data?.files[0].embedding_model).toBe("first");
    });

    it("treats embedding_dimensions of 0 as a real value", async () => {
      serveSearch({
        results: [
          chunk({ filename: "a.pdf", embedding_dimensions: 0 }),
          chunk({ filename: "a.pdf", embedding_dimensions: 512 }),
        ],
      });

      const { result } = await runSearch("term");

      // `== null` guard, so 0 must not be overwritten.
      expect(result.current.data?.files[0].embedding_dimensions).toBe(0);
    });

    it("applies defaults for missing optional fields", async () => {
      serveSearch({ results: [chunk({ filename: "a.pdf" })] });

      const { result } = await runSearch("term");

      expect(result.current.data?.files[0]).toMatchObject({
        source_url: "",
        owner: "",
        size: 0,
        connector_type: "local",
        allowed_users: [],
        allowed_groups: [],
      });
    });

    it("carries ACL fields through when present (#1611)", async () => {
      serveSearch({
        results: [
          chunk({
            filename: "a.pdf",
            allowed_users: ["u1"],
            allowed_groups: ["g1"],
          }),
        ],
      });

      const { result } = await runSearch("term");

      expect(result.current.data?.files[0]).toMatchObject({
        allowed_users: ["u1"],
        allowed_groups: ["g1"],
      });
    });

    it("returns an empty result when the payload has no results key", async () => {
      serveSearch({});

      const { result } = await runSearch("term");

      expect(result.current.data).toEqual({ files: [], warnings: [] });
    });
  });

  describe("warnings", () => {
    it("passes backend warnings straight through (#1499)", async () => {
      serveSearch({
        results: [],
        warnings: [{ code: "embedding_model_missing", models: ["old-model"] }],
      });

      const { result } = await runSearch("term");

      expect(result.current.data?.warnings).toEqual([
        { code: "embedding_model_missing", models: ["old-model"] },
      ]);
    });

    it("normalizes a non-array warnings field to an empty list", async () => {
      serveSearch({ results: [], warnings: "oops" });

      const { result } = await runSearch("term");

      expect(result.current.data?.warnings).toEqual([]);
    });
  });

  describe("errors", () => {
    it("surfaces the backend error message (bubble up search errors to ui)", async () => {
      serveSearch({ error: "index missing" }, 500);

      const { result } = await runSearch("term");

      expect(result.current.isError).toBe(true);
      expect(result.current.error?.message).toBe("index missing");
    });

    it("falls back to the status code when the body has no error field", async () => {
      serveSearch({}, 503);

      const { result } = await runSearch("term");

      expect(result.current.error?.message).toBe(
        "Search failed with status 503",
      );
    });

    it("handles a non-JSON error body", async () => {
      server.use(
        http.post("/api/search", () =>
          HttpResponse.text("<html>bad gateway</html>", { status: 502 }),
        ),
      );

      const { result } = await runSearch("term");

      expect(result.current.isError).toBe(true);
      expect(result.current.error?.message).toBe("Unknown error");
    });

    it("does not retry a failed search", async () => {
      let calls = 0;
      server.use(
        http.post("/api/search", () => {
          calls++;
          return HttpResponse.json({ error: "nope" }, { status: 500 });
        }),
      );

      await runSearch("term");

      // retry: false is set explicitly so errors show immediately.
      expect(calls).toBe(1);
    });
  });
});
