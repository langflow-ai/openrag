import { describe, expect, it } from "vitest";
import {
  buildSearchPayloadFilters,
  extensionMimetypes,
  filterRestrictsChat,
  queryDataRestrictsChat,
} from "./filter-normalization";
import { BASE_SUPPORTED_FILE_TYPES } from "./supported-file-types";

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

const ALL = {
  data_sources: ["*"],
  document_types: ["*"],
  owners: ["*"],
  connector_types: ["*"],
};

describe("filterRestrictsChat", () => {
  it("is false when every dimension is a wildcard and no dates are set", () => {
    expect(filterRestrictsChat(ALL)).toBe(false);
    expect(filterRestrictsChat(undefined)).toBe(false);
  });

  it.each([
    ["data_sources", { ...ALL, data_sources: ["aurora.txt"] }],
    ["document_types", { ...ALL, document_types: ["text/plain"] }],
    ["owners", { ...ALL, owners: ["u1"] }],
    ["connector_types", { ...ALL, connector_types: ["openrag_docs"] }],
    ["created_after", { ...ALL, created_after: AFTER }],
  ])("is true when %s is set", (_field, filters) => {
    expect(filterRestrictsChat(filters)).toBe(true);
  });
});

describe("queryDataRestrictsChat", () => {
  it("reads the saved query_data string", () => {
    expect(
      queryDataRestrictsChat(
        JSON.stringify({ query: "labs.pdf", filters: ALL }),
      ),
    ).toBe(false);
    expect(
      queryDataRestrictsChat(
        JSON.stringify({ filters: { ...ALL, data_sources: ["labs.pdf"] } }),
      ),
    ).toBe(true);
  });

  it("treats missing or malformed data as unscoped", () => {
    expect(queryDataRestrictsChat(null)).toBe(false);
    expect(queryDataRestrictsChat("{not json")).toBe(false);
  });
});

describe("extensionMimetypes", () => {
  it.each([".txt", "*.txt", "txt", "TXT"])("maps %s to text/plain", (query) => {
    expect(extensionMimetypes(query, BASE_SUPPORTED_FILE_TYPES)).toEqual([
      "text/plain",
    ]);
  });

  it("ignores queries that are not a bare extension", () => {
    expect(extensionMimetypes("labs.pdf", BASE_SUPPORTED_FILE_TYPES)).toEqual(
      [],
    );
    expect(
      extensionMimetypes("labs report", BASE_SUPPORTED_FILE_TYPES),
    ).toEqual([]);
    expect(extensionMimetypes(".xyz", BASE_SUPPORTED_FILE_TYPES)).toEqual([]);
  });
});
