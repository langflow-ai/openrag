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
import type { DateRangeValue } from "@/lib/saved-date-range";
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

/** Sets the toolbar date range the way the date picker does. */
function DateRangeSeed({ range }: { range: DateRangeValue | null }) {
  const { setDateRange } = useKnowledgeFilter();
  // biome-ignore lint/correctness/useExhaustiveDependencies: seed once on mount
  useEffect(() => {
    setDateRange(range);
  }, []);
  return null;
}

/** Sets (or, with `null`, clears) the toolbar range on click, like the date picker. */
function SetDateRange({
  label,
  range,
}: {
  label: string;
  range: DateRangeValue | null;
}) {
  const { setDateRange } = useKnowledgeFilter();
  return (
    <button type="button" onClick={() => setDateRange(range)}>
      {label}
    </button>
  );
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

describe("KnowledgeSearchInput suggestions and the date range", () => {
  const SAVED_FILTER = filterFixture({
    query: "",
    filters: {
      data_sources: ["a.pdf"],
      created_after: "2026-01-01T00:00:00.000Z",
      created_before: "2026-01-31T23:59:59.999Z",
    },
  });
  const NOV_20 = new Date(2026, 10, 20);
  // The picker sends the viewer's local day as UTC bounds, with the end bound
  // running through the day's last microsecond (backend precision).
  const NOV_20_START = new Date(2026, 10, 20, 0, 0, 0, 0).toISOString();
  const NOV_20_END = new Date(2026, 10, 20, 23, 59, 59, 999)
    .toISOString()
    .replace(/\.999Z$/, ".999999Z");

  type Filters = Record<string, unknown> | undefined;
  const lastFilters = (requests: SuggestRequest[]) =>
    requests.at(-1)?.filters as Filters;

  async function renderWithControls(
    filter?: KnowledgeFilter,
    initialRange?: DateRangeValue,
  ) {
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <FilterSeed filter={filter} />
        {initialRange && <DateRangeSeed range={initialRange} />}
        <SetDateRange
          label="Pick Nov 20"
          range={{ from: NOV_20, to: NOV_20 }}
        />
        <SetDateRange label="Clear date range" range={null} />
        <KnowledgeSearchInput />
      </>,
      { providers: ["knowledgeFilter"] },
    );
    const input = await screen.findByPlaceholderText(
      "Search your documents...",
    );
    if (filter) await screen.findByText("Reports");
    return { user, input };
  }

  /** Types into the input and returns the filters of the request it triggers. */
  async function suggestFor(
    requests: SuggestRequest[],
    user: ReturnType<typeof userEvent.setup>,
    input: HTMLElement,
    text: string,
  ) {
    requests.length = 0;
    await user.click(input);
    await user.type(input, text);
    await waitFor(() => expect(requests.length).toBeGreaterThan(0));
    return lastFilters(requests);
  }

  it("sends the toolbar range as the viewer's local-day UTC bounds", async () => {
    const requests = serveSuggest();
    const { user, input } = await renderWithControls(undefined, {
      from: NOV_20,
      to: NOV_20,
    });

    const filters = await suggestFor(requests, user, input, "docl");

    expect(filters?.created_after).toBe(NOV_20_START);
    expect(filters?.created_before).toBe(NOV_20_END);
  });

  it("uses a saved filter's range until the toolbar replaces it", async () => {
    const requests = serveSuggest();
    const { user, input } = await renderWithControls(SAVED_FILTER);

    const saved = await suggestFor(requests, user, input, "docl");
    expect(saved?.created_after).toBe("2026-01-01T00:00:00.000Z");
    expect(saved?.created_before).toBe("2026-01-31T23:59:59.999Z");

    await user.click(screen.getByRole("button", { name: "Pick Nov 20" }));
    const replaced = await suggestFor(requests, user, input, "i");

    expect(replaced?.data_sources).toEqual(["a.pdf"]);
    expect(replaced?.created_after).toBe(NOV_20_START);
    expect(replaced?.created_before).toBe(NOV_20_END);
  });

  it("drops a saved filter's dates when the toolbar clears the range", async () => {
    const requests = serveSuggest();
    const { user, input } = await renderWithControls(SAVED_FILTER);

    const saved = await suggestFor(requests, user, input, "docl");
    expect(saved?.created_after).toBe("2026-01-01T00:00:00.000Z");

    await user.click(screen.getByRole("button", { name: "Clear date range" }));
    const cleared = await suggestFor(requests, user, input, "i");

    expect(cleared?.data_sources).toEqual(["a.pdf"]);
    expect(cleared?.created_after).toBeUndefined();
    expect(cleared?.created_before).toBeUndefined();
  });
});
