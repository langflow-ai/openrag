import { describe, expect, it } from "vitest";
import {
  isDateRangeFilterEnabled,
  isDateRangeV2Enabled,
} from "./date-range-filter";

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

describe("isDateRangeV2Enabled", () => {
  it("is enabled for OSS with the flag", () => {
    expect(isDateRangeV2Enabled("oss", true)).toBe(true);
  });

  it("is disabled for OSS without the flag", () => {
    expect(isDateRangeV2Enabled("oss", false)).toBe(false);
  });

  it("is disabled for SaaS even with the flag", () => {
    expect(isDateRangeV2Enabled("saas", true)).toBe(false);
  });

  it.each([null, undefined])("is disabled when the flag is %s", (flag) => {
    expect(isDateRangeV2Enabled("oss", flag)).toBe(false);
  });

  it.each([null, undefined, ""])("is disabled for run mode %s", (runMode) => {
    expect(isDateRangeV2Enabled(runMode, true)).toBe(false);
  });
});
