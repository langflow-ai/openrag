import { act, fireEvent } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import {
  countWithinCoverage,
  MAX_HISTOGRAM_DAYS,
} from "@/lib/knowledge-date-range";
import { authPresets, withAuth } from "@/test-utils/fixtures/auth";
import {
  renderWithProviders,
  screen,
  waitFor,
  within,
} from "@/test-utils/render";
import { KnowledgeDateRangeFilter } from "./knowledge-date-range-filter";

let histogramRequests: URL[] = [];

const histogramHandler = http.get(
  "/api/files/upload-histogram",
  ({ request }) => {
    histogramRequests.push(new URL(request.url));
    return HttpResponse.json({
      total: 10,
      days: { "2024-06-20": 1, "2024-06-19": 3, "2024-06-10": 6 },
    });
  },
);

async function click(el: HTMLElement) {
  await act(async () => {
    fireEvent.click(el);
  });
}

/** Surfaces the effective range bounds retrieval would use. */
function Probe() {
  const { effectiveDateRange } = useKnowledgeFilter();
  return (
    <output aria-label="Effective range start">
      {effectiveDateRange.createdAfter ?? "none"}
    </output>
  );
}

function renderV2(v2 = true) {
  renderWithProviders(
    <>
      <KnowledgeDateRangeFilter />
      <Probe />
    </>,
    {
      providers: ["auth", "knowledgeFilter"],
      auth: withAuth(authPresets.admin, {
        me: { run_mode: "oss", date_range_v2: v2 },
      }),
      handlers: [histogramHandler],
    },
  );
}

describe("KnowledgeDateRangeV2", () => {
  beforeEach(() => {
    histogramRequests = [];
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2024, 5, 20, 12));
  });
  afterEach(() => vi.useRealTimers());

  it("keeps the classic picker when the flag is off", async () => {
    renderV2(false);
    const trigger = await screen.findByRole("button", {
      name: /filter by date range/i,
    });
    await click(trigger);
    expect(await screen.findByText("Apply filter")).toBeInTheDocument();
    expect(screen.queryByText("Applies to")).not.toBeInTheDocument();
  });

  it("shows the compact picker with counts when the flag is on", async () => {
    renderV2();
    await click(
      await screen.findByRole("button", { name: /filter by date range/i }),
    );
    expect(screen.queryByText("Applies to")).not.toBeInTheDocument();
    expect(screen.getByText("Quick ranges")).toBeInTheDocument();
    expect((await screen.findAllByText("10")).length).toBeGreaterThan(0);
    expect(screen.getByText("Custom range")).toBeInTheDocument();
  });

  it("applies a preset as the toolbar range", async () => {
    renderV2();
    await click(
      await screen.findByRole("button", { name: /filter by date range/i }),
    );
    await click(await screen.findByRole("button", { name: /^Today/ }));
    await waitFor(() => {
      expect(
        screen.getByLabelText("Effective range start"),
      ).not.toHaveTextContent("none");
    });
  });

  it("opens the custom range view and goes back", async () => {
    renderV2();
    await click(
      await screen.findByRole("button", { name: /filter by date range/i }),
    );
    await click(await screen.findByText("Custom range"));
    expect(
      await screen.findByRole("button", { name: "Apply filter" }),
    ).toBeDisabled();
    await click(screen.getByRole("button", { name: "Back" }));
    expect(await screen.findByText("Quick ranges")).toBeInTheDocument();
  });

  it("offers quarter presets", async () => {
    renderV2();
    await click(
      await screen.findByRole("button", { name: /filter by date range/i }),
    );
    expect(
      await screen.findByRole("button", { name: /^This quarter/ }),
    ).toBeInTheDocument();
    await click(screen.getByRole("button", { name: /^Last quarter/ }));
    // 2024-06-20 is in Q2, so last quarter starts on 2024-01-01.
    await waitFor(() =>
      expect(screen.getByLabelText("Effective range start")).toHaveTextContent(
        new Date(2024, 0, 1).toISOString().slice(0, 10),
      ),
    );
  });

  it("lets the calendar go back past the histogram cap", async () => {
    renderV2();
    await click(
      await screen.findByRole("button", { name: /filter by date range/i }),
    );
    await click(await screen.findByText("Custom range"));
    const prev = await screen.findByRole("button", { name: /previous month/i });
    for (let i = 0; i < 30; i++) await click(prev);
    expect(prev).toBeEnabled();
  });

  it("never requests a histogram window older than the cap", async () => {
    renderV2();
    await click(
      await screen.findByRole("button", { name: /filter by date range/i }),
    );
    await waitFor(() => expect(histogramRequests.length).toBeGreaterThan(0));
    const start = new Date(
      histogramRequests[0].searchParams.get("start") ?? "",
    );
    const ageDays = (Date.now() - start.getTime()) / 86_400_000;
    expect(ageDays).toBeLessThanOrEqual(MAX_HISTOGRAM_DAYS + 1);
  });
});

const AFTER = "2026-10-07T07:00:00.000Z";
const BEFORE = "2026-10-11T06:59:59.999999Z";
const savedFilter = {
  id: "f1",
  name: "Saved",
  description: "",
  owner: "user-1",
  created_at: "",
  updated_at: "",
  query_data: JSON.stringify({
    query: "",
    filters: {
      data_sources: ["*"],
      document_types: ["*"],
      owners: ["*"],
      connector_types: ["*"],
      created_after: AFTER,
      created_before: BEFORE,
    },
    date_range_context: {
      from: "2026-10-07",
      to: "2026-10-10",
      timezone: "America/Los_Angeles",
    },
    limit: 10,
    scoreThreshold: 0,
    color: "zinc",
    icon: "filter",
  }),
};

function Controls() {
  const { setSelectedFilter, setDateRange } = useKnowledgeFilter();
  return (
    <>
      <button type="button" onClick={() => setSelectedFilter(savedFilter)}>
        select-saved
      </button>
      <button
        type="button"
        onClick={() =>
          setDateRange({ from: new Date(2024, 5, 1), to: new Date(2024, 5, 3) })
        }
      >
        toolbar-range
      </button>
    </>
  );
}

function renderControlled() {
  renderWithProviders(
    <>
      <KnowledgeDateRangeFilter />
      <Controls />
      <Probe />
    </>,
    {
      providers: ["auth", "knowledgeFilter"],
      auth: withAuth(authPresets.admin, {
        me: { run_mode: "oss", date_range_v2: true },
      }),
      handlers: [histogramHandler],
    },
  );
}

describe("KnowledgeDateRangeV2 clearing", () => {
  beforeEach(() => {
    histogramRequests = [];
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2024, 5, 20, 12));
  });
  afterEach(() => vi.useRealTimers());

  it("clears a toolbar range", async () => {
    renderControlled();
    await click(await screen.findByRole("button", { name: "toolbar-range" }));
    expect(
      screen.getByLabelText("Effective range start"),
    ).not.toHaveTextContent("none");
    await click(
      await screen.findByRole("button", { name: "Clear date range" }),
    );
    expect(screen.getByLabelText("Effective range start")).toHaveTextContent(
      "none",
    );
  });

  it("clears to an explicit 'Any time', not back to the saved bounds", async () => {
    renderControlled();
    await click(await screen.findByRole("button", { name: "select-saved" }));
    expect(screen.getByLabelText("Effective range start")).toHaveTextContent(
      AFTER,
    );
    await click(
      await screen.findByRole("button", { name: "Clear date range" }),
    );
    expect(screen.getByLabelText("Effective range start")).toHaveTextContent(
      "none",
    );
    expect(
      screen.getByLabelText("Effective range start"),
    ).not.toHaveTextContent(AFTER);
  });
});

describe("KnowledgeDateRangeV2 histogram coverage", () => {
  const DOCS: Record<string, number> = {
    "2024-02-15": 4,
    "2024-03-10": 2,
    "2024-05-05": 7,
    "2024-06-19": 1,
  };

  beforeEach(() => {
    histogramRequests = [];
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2024, 5, 20, 12));
  });
  afterEach(() => vi.useRealTimers());

  it("covers both quarters on June 20 and counts documents in the omitted months", async () => {
    const quarterHandler = http.get(
      "/api/files/upload-histogram",
      ({ request }) => {
        const url = new URL(request.url);
        histogramRequests.push(url);
        const from = new Date(url.searchParams.get("start") ?? "");
        const days = Object.fromEntries(
          Object.entries(DOCS).filter(([key]) => {
            const [y, m, d] = key.split("-").map(Number);
            return new Date(y, m - 1, d) >= from;
          }),
        );
        return HttpResponse.json({ total: 14, days });
      },
    );
    renderWithProviders(<KnowledgeDateRangeFilter />, {
      providers: ["auth", "knowledgeFilter"],
      auth: withAuth(authPresets.admin, {
        me: { run_mode: "oss", date_range_v2: true },
      }),
      handlers: [quarterHandler],
    });
    await click(
      await screen.findByRole("button", { name: /filter by date range/i }),
    );

    const last = await screen.findByRole("button", { name: /^Last quarter/ });
    const current = screen.getByRole("button", { name: /^This quarter/ });
    await waitFor(() => {
      expect(within(last).getByText("6")).toBeInTheDocument(); // Jan-Mar
      expect(within(current).getByText("8")).toBeInTheDocument(); // Apr-Jun 20
    });

    const requestStarts = histogramRequests.map(
      (u) => new Date(u.searchParams.get("start") ?? ""),
    );
    expect(requestStarts.some((d) => d <= new Date(2024, 0, 1))).toBe(true);
    const cap = new Date(2024, 5, 20);
    cap.setDate(cap.getDate() - MAX_HISTOGRAM_DAYS - 1);
    for (const d of requestStarts) expect(d >= cap).toBe(true);
  });

  it("reports a count as unavailable when the window starts after the range", () => {
    const range = { from: new Date(2024, 0, 1), to: new Date(2024, 2, 31) };
    expect(
      countWithinCoverage({ "2024-02-15": 4 }, range, new Date(2024, 3, 1)),
    ).toBeNull();
    expect(
      countWithinCoverage({ "2024-02-15": 4 }, range, new Date(2024, 0, 1)),
    ).toBe(4);
  });
});
