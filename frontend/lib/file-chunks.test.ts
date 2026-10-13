import { describe, expect, it } from "vitest";
import { documentScopedSearchQueryData } from "./file-chunks";

describe("documentScopedSearchQueryData", () => {
  it("scopes chunks by stable document id rather than their display title", () => {
    expect(documentScopedSearchQueryData("page-1")).toMatchObject({
      query: "*",
      filters: {
        data_sources: [],
        document_ids: ["page-1"],
      },
    });
  });
});
