import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ParsedQueryData } from "@/contexts/knowledge-filter-context";
import { server } from "@/test-utils/msw/server";
import { createQueryWrapper, renderHook, waitFor } from "@/test-utils/render";
import {
  type ChunkResult,
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
    text: "body",
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
    it("groups chunks by filename and averages their scores", async () => {
      serveSearch({
        results: [
          chunk({ filename: "a.pdf", score: 2 }),
          chunk({ filename: "a.pdf", score: 4 }),
          chunk({ filename: "b.pdf", score: 1 }),
        ],
      });

      const { result } = await runSearch("term");

      const files = result.current.data?.files ?? [];
      expect(files).toHaveLength(2);
      expect(files[0]).toMatchObject({
        filename: "a.pdf",
        chunkCount: 2,
        avgScore: 3,
      });
      expect(files[1]).toMatchObject({ filename: "b.pdf", chunkCount: 1 });
    });

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
