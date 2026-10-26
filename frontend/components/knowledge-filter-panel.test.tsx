import { act, fireEvent } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { useEffect } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useKnowledgeFilter } from "@/contexts/knowledge-filter-context";
import { authPresets, withAuth } from "@/test-utils/fixtures/auth";
import { server } from "@/test-utils/msw/server";
import { renderWithProviders, screen, waitFor } from "@/test-utils/render";
import { KnowledgeFilterPanel } from "./knowledge-filter-panel";

vi.mock("@/lib/analytics", () => ({ trackButton: vi.fn() }));

// The real brand provider reads localStorage; the picker only needs this flag.
vi.mock("@/contexts/brand-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/brand-context")>()),
  useIsCloudBrand: () => false,
}));

const AFTER = "2026-10-07T07:00:00.000Z";
const BEFORE = "2026-10-11T06:59:59.999999Z";
const CONTEXT = {
  from: "2026-10-07",
  to: "2026-10-10",
  timezone: "America/Los_Angeles",
};

const auth = withAuth(authPresets.admin, {
  me: { run_mode: "oss" },
  usersMe: { permissions: ["kf:create", "kf:edit:own"] },
});

type OneSided = { created_after?: string; created_before?: string };

function saved(withDates: boolean, oneSided?: OneSided) {
  return {
    id: "f1",
    name: "PDFs",
    description: "",
    owner: "user-1",
    created_at: "",
    updated_at: "",
    query_data: JSON.stringify({
      query: "",
      filters: {
        data_sources: ["*"],
        document_types: ["application/pdf"],
        owners: ["*"],
        connector_types: ["*"],
        ...(oneSided
          ? oneSided
          : withDates && { created_after: AFTER, created_before: BEFORE }),
      },
      ...((withDates || oneSided) && {
        date_range_context: oneSided ? { timezone: CONTEXT.timezone } : CONTEXT,
      }),
      limit: 10,
      scoreThreshold: 0,
      color: "zinc",
      icon: "filter",
    }),
  };
}

function Harness({
  withDates,
  create = false,
  oneSided,
}: {
  withDates: boolean;
  create?: boolean;
  oneSided?: OneSided;
}) {
  const { setSelectedFilter, dateRange, setDateRange, startCreateMode } =
    useKnowledgeFilter();
  // biome-ignore lint/correctness/useExhaustiveDependencies: select once on mount
  useEffect(() => {
    if (!create) setSelectedFilter(saved(withDates, oneSided));
  }, []);
  return (
    <>
      <button type="button" onClick={startCreateMode}>
        start-create
      </button>
      <button
        type="button"
        onClick={() => setDateRange({ from: new Date(2026, 8, 1) })}
      >
        toolbar-range
      </button>
      <output data-testid="toolbar">{dateRange ? "set" : "none"}</output>
      <KnowledgeFilterPanel />
    </>
  );
}

let putBody: { queryData?: string } | undefined;
let postBody: { name?: string; queryData?: string } | undefined;
// A getter keeps TypeScript from narrowing the callback-assigned variable to never.
const createdBody = () => postBody;

async function renderPanel(withDates: boolean, oneSided?: OneSided) {
  putBody = undefined;
  server.use(
    http.post("/api/search", () => HttpResponse.json({ aggregations: {} })),
    http.put("/api/knowledge-filter/f1", async ({ request }) => {
      putBody = (await request.json()) as { queryData?: string };
      return HttpResponse.json({
        success: true,
        filter: saved(withDates, oneSided),
      });
    }),
  );
  renderWithProviders(<Harness withDates={withDates} oneSided={oneSided} />, {
    providers: ["auth", "knowledgeFilter"],
    auth,
  });
  await screen.findByText("Date ingested");
}

const savedQueryData = () => JSON.parse(putBody?.queryData ?? "{}");

async function click(el: HTMLElement) {
  await act(async () => {
    fireEvent.click(el);
  });
}

async function save() {
  await click(await screen.findByRole("button", { name: /update filter/i }));
  await waitFor(() => expect(putBody).toBeDefined());
  return savedQueryData();
}

describe("KnowledgeFilterPanel date ingested", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 9, 23, 12));
  });
  afterEach(() => vi.useRealTimers());

  it("saves an unchanged dated filter with its exact bounds and context", async () => {
    await renderPanel(true);
    const data = await save();
    expect(data.filters.created_after).toBe(AFTER);
    expect(data.filters.created_before).toBe(BEFORE);
    expect(data.filters.document_types).toEqual(["application/pdf"]);
    expect(data.date_range_context).toEqual(CONTEXT);
    expect(data.filters.date_range_context).toBeUndefined();
  });

  it("saves a filter without dates unrestricted", async () => {
    await renderPanel(false);
    const data = await save();
    expect(data.filters).not.toHaveProperty("created_after");
    expect(data.filters).not.toHaveProperty("created_before");
    expect(data).not.toHaveProperty("date_range_context");
  });

  it("clears a saved range by choosing All dates", async () => {
    await renderPanel(true);
    await click(screen.getByRole("button", { name: /–/ }));
    await click(await screen.findByRole("button", { name: "All dates" }));
    await click(screen.getByRole("button", { name: "Apply" }));
    const data = await save();
    expect(data.filters).not.toHaveProperty("created_after");
    expect(data.filters).not.toHaveProperty("created_before");
    expect(data).not.toHaveProperty("date_range_context");
  });

  it("does not save a temporary toolbar range", async () => {
    await renderPanel(false);
    await click(screen.getByRole("button", { name: "toolbar-range" }));
    expect(screen.getByTestId("toolbar")).toHaveTextContent("set");
    const data = await save();
    expect(data.filters).not.toHaveProperty("created_after");
    expect(data).not.toHaveProperty("date_range_context");
  });

  it("creates a filter without dates even when a toolbar range was active", async () => {
    postBody = undefined;
    server.use(
      http.post("/api/search", () => HttpResponse.json({ aggregations: {} })),
      http.post("/api/knowledge-filter", async ({ request }) => {
        postBody = (await request.json()) as typeof postBody;
        return HttpResponse.json({ success: true, filter: saved(false) });
      }),
    );
    renderWithProviders(<Harness withDates={false} create />, {
      providers: ["auth", "knowledgeFilter"],
      auth,
    });
    await click(screen.getByRole("button", { name: "toolbar-range" }));
    expect(screen.getByTestId("toolbar")).toHaveTextContent("set");

    await click(screen.getByRole("button", { name: "start-create" }));
    await screen.findByText("Date ingested");
    expect(screen.getByTestId("toolbar")).toHaveTextContent("none");
    expect(
      screen.getByRole("button", { name: /filter by date ingested/i }),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/name/i), {
      target: { value: "New filter" },
    });
    await click(screen.getByRole("button", { name: /create filter/i }));
    await waitFor(() => expect(createdBody()).toBeDefined());

    const data = JSON.parse(createdBody()?.queryData ?? "{}");
    expect(data.filters).not.toHaveProperty("created_after");
    expect(data.filters).not.toHaveProperty("created_before");
    expect(data).not.toHaveProperty("date_range_context");
  });

  it.each([
    ["created_after", { created_after: "2026-10-07T07:00:00.000Z" }],
    ["created_before", { created_before: "2026-10-11T06:59:59.999999Z" }],
  ])("keeps a %s-only range when the field is applied without edits", async (key, oneSided) => {
    await renderPanel(true, oneSided);
    await click(screen.getByRole("button", { name: /^(From|Until) / }));
    await click(await screen.findByRole("button", { name: "Apply" }));

    const data = await save();
    expect(data.filters[key]).toBe(Object.values(oneSided)[0]);
    const other = key === "created_after" ? "created_before" : "created_after";
    expect(data.filters).not.toHaveProperty(other);
  });

  it("offers All dates, 30/60/90 days and a custom range", async () => {
    await renderPanel(false);
    await click(
      screen.getByRole("button", { name: /filter by date ingested/i }),
    );
    for (const name of [
      "All dates",
      "Last 30 days",
      "Last 60 days",
      "Last 90 days",
      "Custom date range",
    ]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "All dates" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("saves a Last 30 days selection as full local-day bounds", async () => {
    await renderPanel(false);
    await click(
      screen.getByRole("button", { name: /filter by date ingested/i }),
    );
    await click(screen.getByRole("button", { name: "Last 30 days" }));
    await click(screen.getByRole("button", { name: "Apply" }));

    const data = await save();
    // today is faked as 2026-10-23, so 30 days is Sep 24 - Oct 23 inclusive.
    expect(new Date(data.filters.created_after).getTime()).toBe(
      new Date(2026, 8, 24).getTime(),
    );
    expect(new Date(data.filters.created_before).getTime()).toBeGreaterThan(
      new Date(2026, 9, 23, 23, 59).getTime(),
    );
    expect(data.date_range_context.from).toBe("2026-09-24");
    expect(data.date_range_context.to).toBe("2026-10-23");
  });

  it("discards the draft on Cancel", async () => {
    await renderPanel(false);
    await click(
      screen.getByRole("button", { name: /filter by date ingested/i }),
    );
    await click(screen.getByRole("button", { name: "Last 90 days" }));
    await click(screen.getByRole("button", { name: "Cancel" }));

    const data = await save();
    expect(data.filters).not.toHaveProperty("created_after");
  });

  it("sets From and To through the date fields", async () => {
    await renderPanel(false);
    await click(
      screen.getByRole("button", { name: /filter by date ingested/i }),
    );
    await click(screen.getByRole("button", { name: "Custom date range" }));
    expect(screen.getByRole("button", { name: "From date" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );

    const dayButton = (n: number) =>
      screen
        .getAllByRole("gridcell")
        .find(
          (c) =>
            c.tagName === "BUTTON" &&
            !c.className.includes("day-outside") &&
            c.textContent === String(n),
        ) as HTMLElement;
    await click(dayButton(7));
    await click(screen.getByRole("button", { name: "To date" }));
    // The To calendar opens on its own value's month (October).
    await click(dayButton(10));
    await click(screen.getByRole("button", { name: "Apply" }));

    const data = await save();
    // Custom starts as Sep 24 - Oct 23, so the From calendar opens on September.
    expect(data.date_range_context.from).toBe("2026-09-07");
    // A To before the draft's start would invert the range; the field keeps it
    // disabled, so the To pick above is the first selectable day on or after From.
    expect(data.date_range_context.to).toBe("2026-10-10");
  });
});
