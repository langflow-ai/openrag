import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test-utils/msw/server";
import {
  act,
  createQueryWrapper,
  renderHook,
  waitFor,
} from "@/test-utils/render";
import {
  type SearchSuggestResult,
  SUGGEST_KEYWORD_DEBOUNCE_MS,
  useSearchSuggestions,
} from "./useGetSearchSuggestions";

interface SuggestRequest {
  query: string;
  semantic: boolean;
  filters: Record<string, string[]>;
  scoreThreshold?: number;
}

function result(
  phase: "keyword" | "semantic",
  query: string,
): SearchSuggestResult {
  return {
    phase,
    query,
    suggestions: [{ text: `${query}-${phase}`, files: 1, chunks: 2 }],
    files: [],
  };
}

function serveSuggest() {
  const requests: SuggestRequest[] = [];
  server.use(
    http.post("/api/search/suggest", async ({ request }) => {
      const body = (await request.json()) as SuggestRequest;
      requests.push(body);
      return HttpResponse.json(
        result(body.semantic ? "semantic" : "keyword", body.query),
      );
    }),
  );
  return requests;
}

describe("useSearchSuggestions", () => {
  it("sends a keyword request first, then upgrades to the semantic result", async () => {
    const requests = serveSuggest();
    const { result: hook } = renderHook(
      () => useSearchSuggestions("docling", undefined),
      { wrapper: createQueryWrapper() },
    );

    await waitFor(() => expect(hook.current.data?.phase).toBe("semantic"));

    expect(requests.map((r) => r.semantic)).toEqual(
      expect.arrayContaining([false, true]),
    );
    expect(hook.current.data?.suggestions[0].text).toBe("docling-semantic");
    expect(hook.current.isRefining).toBe(false);
  });

  it("sends nothing below the minimum length", async () => {
    const requests = serveSuggest();
    const { result: hook } = renderHook(
      () => useSearchSuggestions("d", undefined),
      { wrapper: createQueryWrapper() },
    );

    await new Promise((resolve) =>
      setTimeout(resolve, SUGGEST_KEYWORD_DEBOUNCE_MS + 100),
    );

    expect(requests).toHaveLength(0);
    expect(hook.current.data).toBeUndefined();
  });

  it("does not request anything while disabled", async () => {
    const requests = serveSuggest();
    renderHook(() => useSearchSuggestions("docling", undefined, false), {
      wrapper: createQueryWrapper(),
    });

    await new Promise((resolve) =>
      setTimeout(resolve, SUGGEST_KEYWORD_DEBOUNCE_MS + 100),
    );

    expect(requests).toHaveLength(0);
  });

  it("forwards active filters and drops the wildcard sentinel", async () => {
    const requests = serveSuggest();
    renderHook(
      () =>
        useSearchSuggestions("docling", {
          data_sources: ["a.pdf"],
          owners: ["*"],
        }),
      { wrapper: createQueryWrapper() },
    );

    await waitFor(() => expect(requests.length).toBeGreaterThan(0));
    expect(requests[0].filters).toEqual({ data_sources: ["a.pdf"] });
  });

  it("forwards the base score threshold on both phases", async () => {
    const requests = serveSuggest();
    renderHook(() => useSearchSuggestions("docling", undefined, true, 2.5), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(requests.some((r) => r.semantic)).toBe(true));
    expect(requests.map((r) => r.scoreThreshold)).toEqual(
      expect.arrayContaining([2.5]),
    );
    expect(requests.every((r) => r.scoreThreshold === 2.5)).toBe(true);
  });

  it("lowers the threshold for a short single token like the main search", async () => {
    const requests = serveSuggest();
    renderHook(() => useSearchSuggestions("docl", undefined, true, 2.5), {
      wrapper: createQueryWrapper(),
    });

    await waitFor(() => expect(requests.some((r) => r.semantic)).toBe(true));
    expect(requests.every((r) => r.scoreThreshold === 1.0)).toBe(true);
  });

  it("reports an error when the keyword request fails and nothing is cached", async () => {
    server.use(
      http.post("/api/search/suggest", () =>
        HttpResponse.json(
          { error: "Suggestions unavailable" },
          { status: 500 },
        ),
      ),
    );
    const { result: hook } = renderHook(
      () => useSearchSuggestions("docling", undefined),
      { wrapper: createQueryWrapper() },
    );

    await waitFor(() => expect(hook.current.isError).toBe(true));
    expect(hook.current.data).toBeUndefined();
    expect(hook.current.isRefining).toBe(false);
  });

  it("keeps showing keyword results when only the semantic request fails", async () => {
    server.use(
      http.post("/api/search/suggest", async ({ request }) => {
        const body = (await request.json()) as SuggestRequest;
        if (body.semantic) {
          return HttpResponse.json({ error: "x" }, { status: 502 });
        }
        return HttpResponse.json(result("keyword", body.query));
      }),
    );
    const { result: hook } = renderHook(
      () => useSearchSuggestions("docling", undefined),
      { wrapper: createQueryWrapper() },
    );

    await waitFor(() => expect(hook.current.data?.phase).toBe("keyword"));
    await waitFor(() => expect(hook.current.isRefining).toBe(false));
    expect(hook.current.isError).toBe(false);
  });

  it("only debounces after typing pauses, collapsing a burst into one keyword request", async () => {
    const requests = serveSuggest();
    const { rerender } = renderHook(
      ({ q }) => useSearchSuggestions(q, undefined),
      { wrapper: createQueryWrapper(), initialProps: { q: "" } },
    );

    for (const q of ["do", "doc", "docl", "docli"]) {
      await act(async () => {
        rerender({ q });
        await new Promise((resolve) => setTimeout(resolve, 40));
      });
    }

    await waitFor(() =>
      expect(requests.some((r) => !r.semantic && r.query === "docli")).toBe(
        true,
      ),
    );
    const keywordQueries = requests
      .filter((r) => !r.semantic)
      .map((r) => r.query);
    expect(keywordQueries).toEqual(["docli"]);
  });
});
