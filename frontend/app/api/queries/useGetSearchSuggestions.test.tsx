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
