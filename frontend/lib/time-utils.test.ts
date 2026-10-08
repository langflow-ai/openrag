import { describe, expect, it } from "vitest";
import { toUtcDayEndISOString, toUtcDayStartISOString } from "./time-utils";

describe("toUtcDayStartISOString", () => {
  it("sets time to local midnight (00:00:00.000)", () => {
    const date = new Date("2024-03-15T15:30:45.123");
    const result = toUtcDayStartISOString(date);
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
    toUtcDayStartISOString(date);
    expect(date.getTime()).toBe(original);
  });

  it("returns a valid ISO 8601 string", () => {
    const date = new Date("2024-03-15");
    const result = toUtcDayStartISOString(date);
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
    expect(new Date(result).getTime()).not.toBeNaN();
  });
});

describe("toUtcDayEndISOString", () => {
  it("sets time to local end-of-day (23:59:59.999)", () => {
    const date = new Date("2024-03-15T10:00:00");
    const result = toUtcDayEndISOString(date);
    const d = new Date(result);
    expect(d.getHours()).toBe(23);
    expect(d.getMinutes()).toBe(59);
    expect(d.getSeconds()).toBe(59);
    expect(d.getMilliseconds()).toBe(999);
  });

  it("does not mutate the input date", () => {
    const date = new Date("2024-06-01T12:00:00");
    const original = date.getTime();
    toUtcDayEndISOString(date);
    expect(date.getTime()).toBe(original);
  });

  it("returns a valid ISO 8601 string", () => {
    const date = new Date("2024-03-15");
    const result = toUtcDayEndISOString(date);
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
    expect(new Date(result).getTime()).not.toBeNaN();
  });

  it("end is later than start for the same input date", () => {
    const date = new Date("2024-03-15");
    const start = toUtcDayStartISOString(date);
    const end = toUtcDayEndISOString(date);
    expect(new Date(end).getTime()).toBeGreaterThan(new Date(start).getTime());
  });
});
