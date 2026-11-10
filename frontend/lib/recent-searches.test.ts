import { beforeEach, describe, expect, it } from "vitest";
import {
  pushRecentSearch,
  RECENT_SEARCHES_MAX,
  readRecentSearches,
  recentSearchesKey,
  writeRecentSearches,
} from "./recent-searches";

describe("pushRecentSearch", () => {
  it("puts the newest query first", () => {
    expect(pushRecentSearch(["a query"], "b query")).toEqual([
      "b query",
      "a query",
    ]);
  });

  it("moves a repeated query to the front, ignoring case and spacing", () => {
    expect(
      pushRecentSearch(["first", "Docling  Serve", "last"], " docling serve "),
    ).toEqual(["docling serve", "first", "last"]);
  });

  it("ignores blank input", () => {
    const list = ["kept"];
    expect(pushRecentSearch(list, "   ")).toBe(list);
  });

  it("evicts the least recently used entry beyond the cap", () => {
    const full = Array.from({ length: RECENT_SEARCHES_MAX }, (_, i) => `q${i}`);
    const next = pushRecentSearch(full, "new");
    expect(next).toHaveLength(RECENT_SEARCHES_MAX);
    expect(next[0]).toBe("new");
    expect(next).not.toContain(`q${RECENT_SEARCHES_MAX - 1}`);
  });
});

describe("recent search storage", () => {
  beforeEach(() => localStorage.clear());

  it("keeps one list per user", () => {
    writeRecentSearches(recentSearchesKey("u1"), ["mine"]);
    expect(readRecentSearches(recentSearchesKey("u2"))).toEqual([]);
    expect(readRecentSearches(recentSearchesKey("u1"))).toEqual(["mine"]);
  });

  it("returns an empty list for corrupt or non-array data", () => {
    const key = recentSearchesKey("u1");
    localStorage.setItem(key, "{not json");
    expect(readRecentSearches(key)).toEqual([]);
    localStorage.setItem(key, JSON.stringify({ a: 1 }));
    expect(readRecentSearches(key)).toEqual([]);
  });

  it("drops non-string entries", () => {
    const key = recentSearchesKey("u1");
    localStorage.setItem(key, JSON.stringify(["ok", 3, null, "also ok"]));
    expect(readRecentSearches(key)).toEqual(["ok", "also ok"]);
  });
});
