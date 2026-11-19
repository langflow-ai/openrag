import { describe, expect, it } from "vitest";
import {
  buildSearchPayloadFilters,
  isDatasetSelected,
  normalizeDatasetSelection,
  toggleDatasetSelection,
} from "./filter-normalization";

const AFTER = "2026-10-07T07:00:00.000Z";
const BEFORE = "2026-10-11T06:59:59.999999Z";

describe("buildSearchPayloadFilters dates", () => {
  it("keeps saved bounds alongside list filters", () => {
    expect(
      buildSearchPayloadFilters({
        document_types: ["application/pdf"],
        owners: ["*"],
        created_after: AFTER,
        created_before: BEFORE,
      }),
    ).toEqual({
      document_types: ["application/pdf"],
      created_after: AFTER,
      created_before: BEFORE,
    });
  });

  it("treats a date-only filter as an active filter", () => {
    expect(buildSearchPayloadFilters({ created_after: AFTER })).toEqual({
      created_after: AFTER,
    });
  });

  it("drops blank bounds and stays undefined for filters without dates", () => {
    expect(
      buildSearchPayloadFilters({ created_after: "", created_before: "" }),
    ).toBeUndefined();
    expect(buildSearchPayloadFilters({ data_sources: ["*"] })).toBeUndefined();
  });

  it("omits dates when the caller supplies its own effective bounds", () => {
    expect(
      buildSearchPayloadFilters(
        { document_types: ["application/pdf"], created_after: AFTER },
        { includeDates: false },
      ),
    ).toEqual({ document_types: ["application/pdf"] });
  });
});

describe("buildSearchPayloadFilters datasets", () => {
  it("omits datasets when missing, malformed or the wildcard", () => {
    expect(buildSearchPayloadFilters({ datasets: undefined })).toBeUndefined();
    expect(buildSearchPayloadFilters({ datasets: ["*"] })).toBeUndefined();
    expect(buildSearchPayloadFilters({ datasets: ["a", "*"] })).toBeUndefined();
    expect(
      buildSearchPayloadFilters({
        datasets: "ds-1" as unknown as string[],
      }),
    ).toBeUndefined();
  });

  it("keeps an explicit list and keeps [] (search no datasets)", () => {
    expect(buildSearchPayloadFilters({ datasets: ["ds-1", "ds-2"] })).toEqual({
      datasets: ["ds-1", "ds-2"],
    });
    expect(buildSearchPayloadFilters({ datasets: [] })).toEqual({
      datasets: [],
    });
  });

  it("is stable when applied twice, as chat does", () => {
    const once = buildSearchPayloadFilters({
      owners: ["me"],
      datasets: [],
    });
    expect(buildSearchPayloadFilters(once)).toEqual(once);
  });

  it("drops datasets for document-only callers", () => {
    expect(
      buildSearchPayloadFilters(
        { owners: ["me"], datasets: ["ds-1"] },
        { includeDatasets: false },
      ),
    ).toEqual({ owners: ["me"] });
    expect(
      buildSearchPayloadFilters({ datasets: [] }, { includeDatasets: false }),
    ).toBeUndefined();
  });
});

describe("dataset selection helpers", () => {
  const visible = ["a", "b", "c"];

  it("parses selections", () => {
    expect(normalizeDatasetSelection(undefined)).toBeUndefined();
    expect(normalizeDatasetSelection(null)).toBeUndefined();
    expect(normalizeDatasetSelection(["*"])).toBeUndefined();
    expect(normalizeDatasetSelection([])).toEqual([]);
    expect(normalizeDatasetSelection(["a", 3, "b"])).toEqual(["a", "b"]);
  });

  it("treats missing and wildcard as every dataset selected", () => {
    expect(isDatasetSelected(undefined, "a")).toBe(true);
    expect(isDatasetSelected(["*"], "a")).toBe(true);
    expect(isDatasetSelected(["b"], "a")).toBe(false);
    expect(isDatasetSelected([], "a")).toBe(false);
  });

  it("unticking from all writes the remaining ids", () => {
    expect(toggleDatasetSelection(undefined, visible, "b", false)).toEqual([
      "a",
      "c",
    ]);
    expect(toggleDatasetSelection(["*"], visible, "a", false)).toEqual([
      "b",
      "c",
    ]);
  });

  it("ticking the last missing dataset goes back to all", () => {
    expect(
      toggleDatasetSelection(["a", "c"], visible, "b", true),
    ).toBeUndefined();
  });

  it("ticks from none and keeps ids that are no longer visible", () => {
    expect(toggleDatasetSelection([], visible, "a", true)).toEqual(["a"]);
    expect(toggleDatasetSelection(["a", "gone"], visible, "a", true)).toEqual([
      "a",
      "gone",
    ]);
    expect(toggleDatasetSelection(["a", "gone"], visible, "b", true)).toEqual([
      "a",
      "gone",
      "b",
    ]);
  });
});
