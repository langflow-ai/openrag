import { afterEach, describe, expect, it } from "vitest";
import { toLocalDayEndISOString, toLocalDayStartISOString } from "./time-utils";

describe("toLocalDayStartISOString", () => {
  it("sets time to local midnight (00:00:00.000)", () => {
    const date = new Date("2024-03-15T15:30:45.123");
    const result = toLocalDayStartISOString(date);
    const d = new Date(result);
    // getHours/getMinutes/etc. return local time, matching what setHours set
    expect(d.getHours()).toBe(0);
    expect(d.getMinutes()).toBe(0);
    expect(d.getSeconds()).toBe(0);
    expect(d.getMilliseconds()).toBe(0);
  });

  it("does not mutate the input date", () => {
    const date = new Date("2024-06-01T12:00:00");
    const original = date.getTime();
    toLocalDayStartISOString(date);
    expect(date.getTime()).toBe(original);
  });

  it("returns a valid ISO 8601 string", () => {
    const date = new Date("2024-03-15");
    const result = toLocalDayStartISOString(date);
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
    expect(new Date(result).getTime()).not.toBeNaN();
  });
});

describe("toLocalDayEndISOString", () => {
  it("sets time to local end-of-day (23:59:59.999)", () => {
    const date = new Date("2024-03-15T10:00:00");
    const result = toLocalDayEndISOString(date);
    const d = new Date(result);
    expect(d.getHours()).toBe(23);
    expect(d.getMinutes()).toBe(59);
    expect(d.getSeconds()).toBe(59);
    expect(d.getMilliseconds()).toBe(999);
  });

  it("does not mutate the input date", () => {
    const date = new Date("2024-06-01T12:00:00");
    const original = date.getTime();
    toLocalDayEndISOString(date);
    expect(date.getTime()).toBe(original);
  });

  it("returns a valid ISO 8601 string", () => {
    const date = new Date("2024-03-15");
    const result = toLocalDayEndISOString(date);
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.999999Z$/);
    expect(new Date(result).getTime()).not.toBeNaN();
  });

  it("end is later than start for the same input date", () => {
    const date = new Date("2024-03-15");
    const start = toLocalDayStartISOString(date);
    const end = toLocalDayEndISOString(date);
    expect(new Date(end).getTime()).toBeGreaterThan(new Date(start).getTime());
  });
});

describe("local-day filter bounds across timezones", () => {
  const originalTz = process.env.TZ;
  afterEach(() => {
    process.env.TZ = originalTz;
  });

  // 2024-10-06T03:00Z is 8pm Oct 5 in Los Angeles, 11pm Oct 5 in New York,
  // and 8:30am Oct 6 in Kolkata.
  const uploadedAt = Date.parse("2024-10-06T03:00:00.000Z");

  function dayContainsUpload(day: number) {
    const picked = new Date(2024, 9, day); // what the calendar hands back
    const start = Date.parse(toLocalDayStartISOString(picked));
    const end = Date.parse(toLocalDayEndISOString(picked));
    return start <= uploadedAt && uploadedAt <= end;
  }

  it.each([
    { tz: "America/Los_Angeles", localDay: 5 },
    { tz: "America/New_York", localDay: 5 },
    { tz: "UTC", localDay: 6 },
    { tz: "Asia/Kolkata", localDay: 6 },
  ])("in $tz the upload lands on the day it is displayed under ($localDay)", ({
    tz,
    localDay,
  }) => {
    process.env.TZ = tz;
    expect(
      new Date(uploadedAt).toLocaleDateString("en-US", { day: "numeric" }),
    ).toBe(String(localDay));
    expect(dayContainsUpload(localDay)).toBe(true);
    expect(dayContainsUpload(localDay === 5 ? 6 : 5)).toBe(false);
  });

  it("spans exactly one local day, including across a DST change", () => {
    process.env.TZ = "America/New_York";
    // 2024-11-03 is the fall-back day: 25 hours long in New York.
    const picked = new Date(2024, 10, 3);
    const start = Date.parse(toLocalDayStartISOString(picked));
    const end = Date.parse(toLocalDayEndISOString(picked));
    expect(end - start + 1).toBe(25 * 60 * 60 * 1000);
  });
});
