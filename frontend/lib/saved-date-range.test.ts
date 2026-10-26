import { afterEach, describe, expect, it } from "vitest";
import {
  applySelection,
  displayRangeFromSaved,
  foreignTimeZone,
  NO_DATE_RANGE,
  parseSavedDateRange,
  savedRangeFromSelection,
} from "./saved-date-range";

// October 7-10 picked in Los Angeles (PDT, UTC-7): full local days as UTC bounds.
const LA_RANGE = {
  createdAfter: "2026-10-07T07:00:00.000Z",
  createdBefore: "2026-10-11T06:59:59.999999Z",
  context: {
    from: "2026-10-07",
    to: "2026-10-10",
    timezone: "America/Los_Angeles",
  },
};

const originalTZ = process.env.TZ;
afterEach(() => {
  if (originalTZ === undefined) delete process.env.TZ;
  else process.env.TZ = originalTZ;
});

const ymd = (d: Date | undefined) =>
  d && [d.getFullYear(), d.getMonth() + 1, d.getDate()].join("-");

describe("parseSavedDateRange", () => {
  it("returns an empty range for filters saved without dates", () => {
    expect(parseSavedDateRange({ filters: { document_types: ["*"] } })).toEqual(
      {},
    );
    expect(parseSavedDateRange(undefined)).toEqual({});
  });

  it("reads bounds and context", () => {
    expect(
      parseSavedDateRange({
        filters: {
          created_after: LA_RANGE.createdAfter,
          created_before: LA_RANGE.createdBefore,
        },
        date_range_context: LA_RANGE.context,
      }),
    ).toEqual(LA_RANGE);
  });

  it("ignores context when there are no bounds", () => {
    expect(
      parseSavedDateRange({ date_range_context: LA_RANGE.context }),
    ).toEqual({});
  });
});

describe("timezone handling", () => {
  it("restores the saved calendar days, not the viewer's shifted days", () => {
    process.env.TZ = "Europe/London";
    const shown = displayRangeFromSaved(LA_RANGE);
    expect(ymd(shown?.from)).toBe("2026-10-7");
    expect(ymd(shown?.to)).toBe("2026-10-10");
  });

  it("keeps the exact saved bounds when the same days are re-applied elsewhere", () => {
    process.env.TZ = "Europe/London";
    const shown = displayRangeFromSaved(LA_RANGE);
    expect(applySelection(LA_RANGE, shown)).toBe(LA_RANGE);
  });

  it("recomputes bounds in the viewer's timezone once the user edits the range", () => {
    process.env.TZ = "Europe/London";
    const edited = applySelection(LA_RANGE, {
      from: new Date(2026, 9, 7),
      to: new Date(2026, 9, 9),
    });
    // London is on BST (UTC+1) in October.
    expect(edited.createdAfter).toBe("2026-10-06T23:00:00.000Z");
    expect(edited.createdBefore).toBe("2026-10-09T22:59:59.999999Z");
    expect(edited.context).toEqual({
      from: "2026-10-07",
      to: "2026-10-09",
      timezone: "Europe/London",
    });
  });

  it("surfaces the saved timezone only when it differs from the viewer's", () => {
    process.env.TZ = "Europe/London";
    expect(foreignTimeZone(LA_RANGE)).toBe("America/Los_Angeles");
    process.env.TZ = "America/Los_Angeles";
    expect(foreignTimeZone(LA_RANGE)).toBeNull();
    expect(foreignTimeZone(NO_DATE_RANGE)).toBeNull();
  });

  it("derives days from the bounds when a filter has no context", () => {
    process.env.TZ = "UTC";
    const shown = displayRangeFromSaved({
      createdAfter: "2026-10-07T00:00:00.000Z",
      createdBefore: "2026-10-10T23:59:59.999Z",
    });
    expect(ymd(shown?.from)).toBe("2026-10-7");
    expect(ymd(shown?.to)).toBe("2026-10-10");
  });
});

describe("clearing", () => {
  it("clearing a range yields neither bound", () => {
    expect(applySelection(LA_RANGE, null)).toEqual({});
    expect(applySelection(LA_RANGE, {})).toEqual({});
    expect(savedRangeFromSelection(null)).toEqual({});
  });
});
