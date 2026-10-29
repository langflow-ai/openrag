import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { useEffect } from "react";
import { toast } from "sonner";
import { describe, expect, it, vi } from "vitest";
import type { KnowledgeFilter } from "@/app/api/queries/useGetFiltersSearchQuery";
import {
  type SearchSuggestResult,
  SUGGEST_MAX_CHARS,
} from "@/app/api/queries/useGetSearchSuggestions";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { server } from "@/test-utils/msw/server";
import { renderWithProviders } from "@/test-utils/render";
import { mockRouter } from "@/test-utils/router";
import { KnowledgeSearchInput } from "./knowledge-search-input";

vi.mock("@/lib/analytics", () => ({
  trackSearch: vi.fn(),
  trackButton: vi.fn(),
}));

const PAYLOAD: SearchSuggestResult = {
  phase: "semantic",
  query: "docl",
  suggestions: [{ text: "docling", files: 2, chunks: 61 }],
  files: [
    {
      filename: "docling.pdf",
      mimetype: "application/pdf",
      connector_type: "local",
      preview: null,
    },
  ],
};

interface SuggestRequest {
  query: string;
  semantic: boolean;
  scoreThreshold: number;
  filters: Record<string, string[]>;
}

function serveSuggest() {
  const requests: SuggestRequest[] = [];
  server.use(
    http.post("/api/search/suggest", async ({ request }) => {
      requests.push((await request.json()) as SuggestRequest);
      return HttpResponse.json(PAYLOAD);
    }),
  );
  return requests;
}

function filterFixture(queryData: object): KnowledgeFilter {
  return {
    id: "f1",
    name: "Reports",
    description: "",
    query_data: JSON.stringify(queryData),
    owner: "u1",
    created_at: "",
    updated_at: "",
  };
}

/** Selects a filter and exposes the committed query through the DOM. */
function FilterSeed({ filter }: { filter?: KnowledgeFilter }) {
  const { setSelectedFilter, queryOverride } = useKnowledgeFilter();
  // biome-ignore lint/correctness/useExhaustiveDependencies: seed once on mount
  useEffect(() => {
    if (filter) setSelectedFilter(filter);
  }, []);
  return <output data-testid="committed">{queryOverride}</output>;
}

function renderInput(
  props: Parameters<typeof KnowledgeSearchInput>[0] = {},
  filter?: KnowledgeFilter,
) {
  const user = userEvent.setup();
  renderWithProviders(
    <>
      <FilterSeed filter={filter} />
      <KnowledgeSearchInput {...props} />
    </>,
    { providers: ["knowledgeFilter"] },
  );
  return {
    user,
    input: screen.getByPlaceholderText("Search your documents..."),
  };
}

describe("KnowledgeSearchInput suggestions", () => {
  it("opens suggestions while typing in uncontrolled mode", async () => {
    serveSuggest();
    const { user, input } = renderInput();

    await user.click(input);
    await user.type(input, "docl");

    expect(
      await screen.findByRole("option", { name: /docling\.pdf/ }),
    ).toBeInTheDocument();
  });

  it("picking a suggestion fills the input and commits the search", async () => {
    serveSuggest();
    const { user, input } = renderInput();
    await user.click(input);
    await user.type(input, "docl");

    await user.click(await screen.findByRole("option", { name: /61 chunks/ }));

    expect(input).toHaveValue("docling");
    expect(screen.getByTestId("committed")).toHaveTextContent("docling");
  });

  it("picking a file navigates to its chunks with the typed query", async () => {
    serveSuggest();
    const { user, input } = renderInput();
    await user.click(input);
    await user.type(input, "docl");

    await user.click(
      await screen.findByRole("option", { name: /docling\.pdf/ }),
    );

    expect(mockRouter.push).toHaveBeenCalledWith(
      "/knowledge/chunks?filename=docling.pdf&q=docl",
    );
  });

  it("submitting closes the dropdown and commits the typed text", async () => {
    serveSuggest();
    const { user, input } = renderInput();
    await user.click(input);
    await user.type(input, "docl");
    await screen.findByRole("listbox");

    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument(),
    );
    expect(screen.getByTestId("committed")).toHaveTextContent("docl");
  });

  it("stops accepting characters at the cap and shows an error popup", async () => {
    serveSuggest();
    const errorToast = vi.spyOn(toast, "error").mockReturnValue("toast");
    const { user, input } = renderInput();
    await user.click(input);

    await user.type(input, "a".repeat(SUGGEST_MAX_CHARS + 1));

    expect(input).toHaveValue("a".repeat(SUGGEST_MAX_CHARS));
    expect(errorToast).toHaveBeenCalledWith(
      `Search is limited to ${SUGGEST_MAX_CHARS} characters.`,
      expect.anything(),
    );
  });

  it("does not suggest in controlled mode, where results filter live", async () => {
    const requests = serveSuggest();
    const onSearch = vi.fn();
    const { user, input } = renderInput({ value: "", onSearch });

    expect(input).not.toHaveAttribute("role", "combobox");
    await user.type(input, "docl");
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 700));
    });

    expect(onSearch).toHaveBeenCalled();
    expect(requests).toHaveLength(0);
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("sends the selected filter's facets and score threshold", async () => {
    const requests = serveSuggest();
    const filter = filterFixture({
      query: "",
      filters: { data_sources: ["a.pdf"] },
      scoreThreshold: 2.5,
    });
    const { user, input } = renderInput({}, filter);
    await screen.findByText("Reports");

    await user.click(input);
    await user.type(input, "docling");
    await waitFor(() => expect(requests.some((r) => r.semantic)).toBe(true));

    expect(requests.every((r) => r.scoreThreshold === 2.5)).toBe(true);
    expect(requests[0].filters).toEqual({ data_sources: ["a.pdf"] });
  });
});
