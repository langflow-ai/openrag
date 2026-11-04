/**
 * Changing the effective date range must restart pagination: the next /files
 * request carries the new bounds, page 1, and no cursor from the old window.
 */

import { act, fireEvent } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { authPresets } from "@/test-utils/fixtures/auth";
import { renderWithProviders, screen, waitFor } from "@/test-utils/render";
import { setMockLocation } from "@/test-utils/router";
import ProtectedSearchPage from "./page";

const OCT = {
  after: "2026-10-07T07:00:00.000Z",
  before: "2026-10-11T06:59:59.999999Z",
};
const SEPT = {
  after: "2026-09-01T07:00:00.000Z",
  before: "2026-09-30T06:59:59.999999Z",
};

function savedFilter(id: string, range: { after: string; before: string }) {
  return {
    id,
    name: id,
    description: "",
    owner: "u",
    created_at: "",
    updated_at: "",
    query_data: JSON.stringify({
      query: "",
      filters: {
        data_sources: ["*"],
        document_types: ["*"],
        owners: ["*"],
        connector_types: ["*"],
        created_after: range.after,
        created_before: range.before,
      },
      limit: 10,
      scoreThreshold: 0,
      color: "zinc",
      icon: "filter",
    }),
  };
}

const OCT_FILTER = savedFilter("oct", OCT);
const SEPT_FILTER = savedFilter("sept", SEPT);

interface FilesRequest {
  page: string | null;
  afterKey: string | null;
  createdAfter: string | null;
  createdBefore: string | null;
}

let requests: FilesRequest[] = [];

function Controls() {
  const { setSelectedFilter, setDateRange, clearFilter } = useKnowledgeFilter();
  return (
    <>
      <button type="button" onClick={() => setSelectedFilter(OCT_FILTER)}>
        select-oct
      </button>
      <button type="button" onClick={() => setSelectedFilter(SEPT_FILTER)}>
        select-sept
      </button>
      <button type="button" onClick={clearFilter}>
        clear-filter
      </button>
      <button
        type="button"
        onClick={() =>
          setDateRange({ from: new Date(2026, 9, 1), to: new Date(2026, 9, 2) })
        }
      >
        change-range
      </button>
      <button type="button" onClick={() => setDateRange(null)}>
        clear-range
      </button>
    </>
  );
}

async function click(el: HTMLElement) {
  await act(async () => {
    fireEvent.click(el);
  });
}

const last = () => requests[requests.length - 1];

async function renderPage() {
  setMockLocation({ pathname: "/knowledge" });
  renderWithProviders(
    <>
      <Controls />
      <ProtectedSearchPage />
    </>,
    {
      providers: "all",
      auth: authPresets.admin,
      handlers: [
        // 3 pages of 25; every page hands out a cursor for the next one.
        http.get("/api/files", ({ request }) => {
          const p = new URL(request.url).searchParams;
          const page = Number(p.get("page") ?? "1");
          requests.push({
            page: p.get("page"),
            afterKey: p.get("after_key"),
            createdAfter: p.get("created_after"),
            createdBefore: p.get("created_before"),
          });
          return HttpResponse.json({
            files: [],
            total: 75,
            is_approximate: false,
            page,
            page_size: 25,
            after_key: { cursor: `after-page-${page}` },
          });
        }),
        http.post("/api/search", () =>
          HttpResponse.json({ files: [], warnings: [] }),
        ),
        http.get("/api/upload_options", () => HttpResponse.json({})),
        http.get("/api/connectors", () =>
          HttpResponse.json({ connectors: [] }),
        ),
        http.get("/api/connectors/:name/defaults", () => HttpResponse.json({})),
      ],
    },
  );
  await waitFor(() => expect(requests.length).toBeGreaterThan(0));
}

/** Select a saved filter, then page forward to page 2 with its cursor in play. */
async function reachPageTwo(filterButton: string) {
  await click(screen.getByRole("button", { name: filterButton }));
  await waitFor(() => expect(last()?.createdAfter).not.toBeNull());
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Next page" })).toBeEnabled(),
  );
  await click(screen.getByRole("button", { name: "Next page" }));
  await waitFor(() => expect(last().page).toBe("2"));
  expect(last().afterKey).not.toBeNull();
  await screen.findByText(/Page 2 of 3/);
}

// These render the whole page and page through it; the default 5s limit is
// too tight when the full suite runs in parallel.
vi.setConfig({ testTimeout: 20_000 });

describe("Knowledge page date range pagination", () => {
  beforeEach(() => {
    requests = [];
  });

  it("restarts at page 1 without a cursor when the range changes", async () => {
    await renderPage();
    await reachPageTwo("select-oct");
    expect(last().createdAfter).toBe(OCT.after);

    await click(screen.getByRole("button", { name: "change-range" }));

    await waitFor(() => expect(last().createdAfter).not.toBe(OCT.after));
    await waitFor(() => expect(last().page).toBe("1"));
    expect(last().afterKey).toBeNull();
    expect(last().createdAfter).toBeTruthy();
    expect(last().createdBefore).toBeTruthy();
    await screen.findByText(/Page 1 of 3/);
  });

  it("restarts at page 1 without a cursor, and without dates, when the range is cleared", async () => {
    await renderPage();
    await reachPageTwo("select-oct");

    await click(screen.getByRole("button", { name: "clear-range" }));

    await waitFor(() => expect(last().createdAfter).toBeNull());
    await waitFor(() => expect(last().page).toBe("1"));
    expect(last().afterKey).toBeNull();
    // Cleared means cleared: neither bound falls back to the saved filter's.
    expect(last().createdBefore).toBeNull();
    await screen.findByText(/Page 1 of 3/);
  });

  it("restarts at page 1 without a cursor when switching saved filters", async () => {
    await renderPage();
    await reachPageTwo("select-oct");

    await click(screen.getByRole("button", { name: "select-sept" }));

    await waitFor(() => expect(last().createdAfter).toBe(SEPT.after));
    await waitFor(() => expect(last().page).toBe("1"));
    expect(last().afterKey).toBeNull();
    expect(last().createdBefore).toBe(SEPT.before);
    await screen.findByText(/Page 1 of 3/);
  });

  it("restarts at page 1 without dates when the saved filter is cleared", async () => {
    await renderPage();
    await reachPageTwo("select-oct");

    await click(screen.getByRole("button", { name: "clear-filter" }));

    await waitFor(() => expect(last().createdAfter).toBeNull());
    await waitFor(() => expect(last().page).toBe("1"));
    expect(last().afterKey).toBeNull();
    expect(last().createdBefore).toBeNull();
  });
});
