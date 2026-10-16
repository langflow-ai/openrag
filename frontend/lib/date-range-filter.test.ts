import { describe, expect, it } from "vitest";
import { isDateRangeFilterEnabled } from "./date-range-filter";

describe("isDateRangeFilterEnabled", () => {
  it("is enabled for OSS", () => {
    expect(isDateRangeFilterEnabled("oss")).toBe(true);
  });

  it.each([
    "saas",
    "",
    null,
    undefined,
  ])("is disabled for run mode %s", (runMode) => {
    expect(isDateRangeFilterEnabled(runMode)).toBe(false);
  });
});
