import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { server } from "@/test-utils/msw/server";
import { latestSavedFilter } from "./useGetFilterByIdQuery";

const stale = {
  id: "f1",
  name: "stale-test",
  description: "",
  query_data: JSON.stringify({ filters: { data_sources: ["*"] } }),
  owner: "me",
  created_at: "",
  updated_at: "1",
};

describe("latestSavedFilter", () => {
  it("returns null when no filter is selected", async () => {
    await expect(latestSavedFilter(null)).resolves.toBeNull();
  });

  it("returns the saved document when the chat copy is older", async () => {
    const fresh = {
      ...stale,
      query_data: JSON.stringify({ filters: { data_sources: ["aurora.txt"] } }),
      updated_at: "2",
    };
    server.use(
      http.get("/api/knowledge-filter/f1", () =>
        HttpResponse.json({ success: true, filter: fresh }),
      ),
    );

    await expect(latestSavedFilter(stale)).resolves.toEqual(fresh);
  });

  it("keeps the chat copy when the lookup fails", async () => {
    server.use(
      http.get(
        "/api/knowledge-filter/f1",
        () => new HttpResponse(null, { status: 500 }),
      ),
    );

    await expect(latestSavedFilter(stale)).resolves.toEqual(stale);
  });
});
