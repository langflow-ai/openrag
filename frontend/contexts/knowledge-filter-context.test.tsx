import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import {
  KnowledgeFilterProvider,
  useKnowledgeFilter,
} from "./knowledge-filter-context";

const AFTER = "2026-10-07T07:00:00.000Z";
const BEFORE = "2026-10-11T06:59:59.999999Z";

function filter(id: string, queryData: object) {
  return {
    id,
    name: id,
    description: "",
    query_data: JSON.stringify(queryData),
    owner: "u",
    created_at: "",
    updated_at: "",
  };
}

const withDates = filter("pdf-oct", {
  filters: {
    document_types: ["application/pdf"],
    created_after: AFTER,
    created_before: BEFORE,
  },
  date_range_context: {
    from: "2026-10-07",
    to: "2026-10-10",
    timezone: "America/Los_Angeles",
  },
});
const withoutDates = filter("plain", {
  filters: { document_types: ["application/pdf"] },
});

function setup() {
  return renderHook(() => useKnowledgeFilter(), {
    wrapper: ({ children }: { children: ReactNode }) => (
      <KnowledgeFilterProvider>{children}</KnowledgeFilterProvider>
    ),
  });
}

describe("KnowledgeFilterProvider saved date range", () => {
  it("restores saved bounds and display days when a filter is selected", () => {
    const { result } = setup();
    act(() => result.current.setSelectedFilter(withDates));
    expect(result.current.effectiveDateRange).toMatchObject({
      createdAfter: AFTER,
      createdBefore: BEFORE,
    });
    expect(result.current.dateRange?.from?.getDate()).toBe(7);
    expect(result.current.dateRange?.to?.getDate()).toBe(10);
  });

  it("leaves a filter without dates unrestricted", () => {
    const { result } = setup();
    act(() => result.current.setSelectedFilter(withoutDates));
    expect(result.current.dateRange).toBeNull();
    expect(result.current.effectiveDateRange).toEqual({});
  });

  it("keeps a temporary toolbar range separate from the saved one", () => {
    const { result } = setup();
    act(() => result.current.setSelectedFilter(withDates));
    act(() =>
      result.current.setDateRange({
        from: new Date(2026, 9, 1),
        to: new Date(2026, 9, 2),
      }),
    );
    expect(result.current.effectiveDateRange.createdAfter).not.toBe(AFTER);
    expect(result.current.savedDateRange.createdAfter).toBe(AFTER);
    expect(result.current.parsedFilterData?.filters.created_after).toBe(AFTER);
  });

  it("clearing a temporary range removes both bounds instead of falling back", () => {
    const { result } = setup();
    act(() => result.current.setSelectedFilter(withDates));
    act(() => result.current.setDateRange(null));
    expect(result.current.dateRange).toBeNull();
    expect(result.current.effectiveDateRange.createdAfter).toBeUndefined();
    expect(result.current.effectiveDateRange.createdBefore).toBeUndefined();
    expect(result.current.savedDateRange.createdAfter).toBe(AFTER);
  });

  it("drops the temporary range when switching or clearing filters", () => {
    const { result } = setup();
    act(() => result.current.setSelectedFilter(withDates));
    act(() => result.current.setDateRange(null));

    act(() => result.current.setSelectedFilter(withDates));
    expect(result.current.effectiveDateRange.createdAfter).toBe(AFTER);

    act(() => result.current.setDateRange({ from: new Date(2026, 9, 1) }));
    act(() => result.current.setSelectedFilter(withoutDates));
    expect(result.current.effectiveDateRange).toEqual({});

    act(() => result.current.setDateRange({ from: new Date(2026, 9, 1) }));
    act(() => result.current.clearFilter());
    expect(result.current.dateRange).toBeNull();
  });

  it("re-applying the displayed days keeps the exact saved bounds", () => {
    const { result } = setup();
    act(() => result.current.setSelectedFilter(withDates));
    const shown = result.current.dateRange;
    act(() => result.current.setDateRange(shown));
    expect(result.current.effectiveDateRange.createdAfter).toBe(AFTER);
    expect(result.current.effectiveDateRange.createdBefore).toBe(BEFORE);
  });

  it("starts a new filter without dates even with a temporary toolbar range", () => {
    const { result } = setup();
    act(() => result.current.setDateRange({ from: new Date(2026, 9, 1) }));
    expect(result.current.effectiveDateRange.createdAfter).toBeTruthy();

    act(() => result.current.startCreateMode());

    expect(result.current.parsedFilterData?.filters).not.toHaveProperty(
      "created_after",
    );
    expect(result.current.parsedFilterData?.filters).not.toHaveProperty(
      "created_before",
    );
    expect(result.current.parsedFilterData?.dateRangeContext).toBeUndefined();
    expect(result.current.dateRange).toBeNull();
    expect(result.current.effectiveDateRange).toEqual({});
  });
});
