import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { refreshConsoleStatusQueries } from "./refresh";

describe("refreshConsoleStatusQueries", () => {
  it("refetches status and provider health when the provider query is enabled", () => {
    const calls: string[] = [];
    refreshConsoleStatusQueries(
      () => calls.push("status"),
      () => calls.push("provider"),
      true,
    );
    assert.deepEqual(calls, ["status", "provider"]);
  });

  it("skips provider health refetch when the provider query is disabled", () => {
    const calls: string[] = [];
    refreshConsoleStatusQueries(
      () => calls.push("status"),
      () => calls.push("provider"),
      false,
    );
    assert.deepEqual(calls, ["status"]);
  });
});
