import { act, fireEvent } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders, screen, waitFor } from "@/test-utils/render";
import { KnowledgeDateRangeFilter } from "./knowledge-date-range-filter";

let histogramRequests: URL[] = [];
let mockRunMode: string | null = "oss";

vi.mock("@/contexts/auth-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/auth-context")>()),
  useAuth: () => ({ runMode: mockRunMode }),
}));

vi.mock("@/contexts/brand-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/brand-context")>()),
  useIsCloudBrand: () => false,
}));

const histogramHandler = http.get(
  "/api/files/upload-histogram",
  ({ request }) => {
    histogramRequests.push(new URL(request.url));
    return HttpResponse.json({
      total: 10,
      days: {
        "2024-06-20": 1,
        "2024-06-19": 3,
        "2024-06-10": 6,
        "2024-05-15": 2,
      },
    });
  },
);

// Radix Popover ignores userEvent pointer sequences in JSDOM; fireEvent.click opens it.
async function click(el: HTMLElement) {
  await act(async () => {
    fireEvent.click(el);
  });
}

function renderFilter() {
  renderWithProviders(<KnowledgeDateRangeFilter />, {
    providers: ["knowledgeFilter"],
    handlers: [histogramHandler],
  });
}

async function openPopover() {
  await click(screen.getByRole("button", { name: /date range/i }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /any time/i })).toHaveTextContent(
      "10",
    ),
  );
}

function preset(name: RegExp) {
  return screen.getByRole("button", { name });
}

function juneDay(day: number) {
  const cell = screen
    .getAllByRole("gridcell")
    .find(
      (c) =>
        c.tagName === "BUTTON" &&
        !c.className.includes("day-outside") &&
        c.querySelector("[data-day-number]")?.textContent === String(day),
    );
  if (!cell) throw new Error(`June ${day} not found`);
  return cell;
}

const fmt = (d: Date) =>
  d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
const short = (d: Date) =>
  d.toLocaleDateString(undefined, { month: "short", day: "numeric" });

describe("KnowledgeDateRangeFilter", () => {
  // Only Date is faked so act()/Radix timers keep running normally.
  beforeEach(() => {
    mockRunMode = "oss";
    histogramRequests = [];
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2024, 5, 20, 12));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it.each(["saas", null])("is hidden when the run mode is %s", (runMode) => {
    mockRunMode = runMode;
    renderFilter();
    expect(
      screen.queryByRole("button", { name: /filter by date range/i }),
    ).not.toBeInTheDocument();
    expect(histogramRequests).toHaveLength(0);
  });

  it("renders the trigger with the default label", () => {
    renderFilter();
    expect(
      screen.getByRole("button", { name: /filter by date range/i }),
    ).toBeInTheDocument();
    expect(screen.getByText("Date range")).toBeInTheDocument();
  });

  it("only fetches upload counts while the popover is open", async () => {
    renderFilter();
    expect(histogramRequests).toHaveLength(0);
    await openPopover();
    expect(histogramRequests.length).toBeGreaterThan(0);
    expect(histogramRequests[0].searchParams.get("tz")).toBeTruthy();
  });

  it("recomputes today when the picker is reopened after midnight", async () => {
    renderFilter();
    await openPopover();
    await click(preset(/^today/i));
    await click(screen.getByRole("button", { name: /apply/i }));

    act(() => {
      vi.setSystemTime(new Date(2024, 5, 21, 0, 5));
    });
    await click(
      screen.getByRole("button", {
        name: new RegExp(fmt(new Date(2024, 5, 20))),
      }),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /any time/i })).toBeVisible(),
    );

    expect(juneDay(21)).not.toBeDisabled();
    await click(preset(/^today/i));
    await click(screen.getByRole("button", { name: /apply/i }));
    expect(
      screen.getByRole("button", {
        name: new RegExp(fmt(new Date(2024, 5, 21))),
      }),
    ).toBeInTheDocument();
  });

  it("lists quick ranges with their upload counts", async () => {
    renderFilter();
    await openPopover();
    expect(preset(/any time/i)).toHaveTextContent("10");
    expect(preset(/^today/i)).toHaveTextContent("1");
    expect(preset(/yesterday/i)).toHaveTextContent("3");
    expect(preset(/last 7 days/i)).toHaveTextContent("4");
    expect(preset(/last 30 days/i)).toHaveTextContent("10");
    expect(preset(/this month/i)).toHaveTextContent("10");
    expect(preset(/last month/i)).toHaveTextContent("2");
    expect(preset(/any time/i)).toHaveAttribute("aria-pressed", "true");
  });

  it("marks each day with its upload density", async () => {
    renderFilter();
    await openPopover();
    const density = (day: number) =>
      juneDay(day)
        .querySelector("[data-testid='upload-density']")
        ?.getAttribute("data-density");
    expect(density(20)).toBe("low");
    expect(density(19)).toBe("medium");
    expect(density(10)).toBe("high");
    expect(density(11)).toBeUndefined();
  });

  it("previews a preset in the footer and applies it on Apply", async () => {
    renderFilter();
    await openPopover();
    await click(preset(/last 7 days/i));

    expect(preset(/last 7 days/i)).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByText(
        `${short(new Date(2024, 5, 14))} – ${short(new Date(2024, 5, 20))}`,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("4 files")).toBeInTheDocument();
    // Nothing is applied until the user confirms.
    expect(
      screen.queryByRole("button", { name: /clear date range/i }),
    ).not.toBeInTheDocument();

    await click(screen.getByRole("button", { name: "Apply filter" }));
    const expected = `${fmt(new Date(2024, 5, 14))} – ${fmt(new Date(2024, 5, 20))}`;
    expect(screen.getByRole("button", { name: expected })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /last 7 days/i }),
    ).not.toBeInTheDocument();
  });

  it("discards the draft on Cancel", async () => {
    renderFilter();
    await openPopover();
    await click(preset(/yesterday/i));
    await click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByText("Date range")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /clear date range/i }),
    ).not.toBeInTheDocument();
  });

  it("selects a custom range by clicking two calendar days", async () => {
    renderFilter();
    await openPopover();
    await click(juneDay(10));
    await click(juneDay(15));

    expect(
      screen.getByText(
        `${short(new Date(2024, 5, 10))} – ${short(new Date(2024, 5, 15))}`,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("6 files")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { pressed: true }),
    ).not.toBeInTheDocument();

    await click(screen.getByRole("button", { name: "Apply filter" }));
    const expected = `${fmt(new Date(2024, 5, 10))} – ${fmt(new Date(2024, 5, 15))}`;
    expect(screen.getByRole("button", { name: expected })).toHaveTextContent(
      expected,
    );
  });

  it("reopens with the applied range selected", async () => {
    renderFilter();
    await openPopover();
    await click(preset(/last month/i));
    await click(screen.getByRole("button", { name: "Apply filter" }));
    await click(
      screen.getByRole("button", {
        name: `${fmt(new Date(2024, 4, 1))} – ${fmt(new Date(2024, 4, 31))}`,
      }),
    );
    expect(preset(/last month/i)).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("May 2024")).toBeInTheDocument();
  });

  it("clears an applied range from the external clear button", async () => {
    renderFilter();
    await openPopover();
    await click(preset(/last 7 days/i));
    await click(screen.getByRole("button", { name: "Apply filter" }));
    await click(screen.getByRole("button", { name: /clear date range/i }));
    expect(screen.getByText("Date range")).toBeInTheDocument();
  });

  it("clears an applied range by applying Any time", async () => {
    renderFilter();
    await openPopover();
    await click(preset(/last 7 days/i));
    await click(screen.getByRole("button", { name: "Apply filter" }));
    await click(
      screen.getByRole("button", {
        name: `${fmt(new Date(2024, 5, 14))} – ${fmt(new Date(2024, 5, 20))}`,
      }),
    );
    await click(preset(/any time/i));
    expect(screen.getByText("10 files")).toBeInTheDocument();
    await click(screen.getByRole("button", { name: "Apply filter" }));
    expect(screen.getByText("Date range")).toBeInTheDocument();
  });

  it("selects the last N days from a typed number and applies it", async () => {
    renderFilter();
    await openPopover();
    await act(async () => {
      fireEvent.change(
        screen.getByRole("textbox", { name: "Number of days" }),
        {
          target: { value: "45" },
        },
      );
    });

    expect(
      screen.getByText(
        `${short(new Date(2024, 4, 7))} – ${short(new Date(2024, 5, 20))}`,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("12 files")).toBeInTheDocument();

    await click(screen.getByRole("button", { name: "Apply filter" }));
    expect(
      screen.getByRole("button", {
        name: `${fmt(new Date(2024, 4, 7))} – ${fmt(new Date(2024, 5, 20))}`,
      }),
    ).toBeInTheDocument();
  });

  it("ignores non-numeric input and clears the draft when emptied", async () => {
    renderFilter();
    await openPopover();
    const input = screen.getByRole("textbox", { name: "Number of days" });
    await act(async () => {
      fireEvent.change(input, { target: { value: "7a" } });
    });
    expect(input).toHaveValue("7");
    expect(preset(/last 7 days/i)).toHaveAttribute("aria-pressed", "true");

    await act(async () => {
      fireEvent.change(input, { target: { value: "" } });
    });
    expect(preset(/any time/i)).toHaveAttribute("aria-pressed", "true");
  });
});
