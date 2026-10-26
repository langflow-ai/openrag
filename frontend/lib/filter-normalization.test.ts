import { describe, expect, it } from "vitest";
import { buildSearchPayloadFilters } from "./filter-normalization";

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
