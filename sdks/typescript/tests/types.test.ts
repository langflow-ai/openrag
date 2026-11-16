import { describe, expect, it } from "vitest";
import type { SearchFilters } from "../src";

describe("SearchFilters", () => {
  it("accepts owner and connector type filters", () => {
    const filters: SearchFilters = {
      data_sources: ["api-docs.pdf"],
      document_types: ["application/pdf"],
      owners: ["user@example.com"],
      connector_types: ["google_drive"],
    };

    expect(filters).toEqual({
      data_sources: ["api-docs.pdf"],
      document_types: ["application/pdf"],
      owners: ["user@example.com"],
      connector_types: ["google_drive"],
    });
  });
});
