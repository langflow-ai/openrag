import { describe, expect, it } from "vitest";
import {
  createUrlSourcePayload,
  INITIAL_URL_SOURCE_FORM,
  isUrlSourceFormValid,
  lines,
} from "./form";

describe("URL source form helpers", () => {
  it("normalizes multiline settings and applies page-only limits", () => {
    const form = {
      ...INITIAL_URL_SOURCE_FORM,
      name: "Docs",
      starting_url: "https://docs.example.com/guides",
      scope: "page" as const,
      additional_hosts: " assets.example.com\n\ncdn.example.com ",
      include_paths: " /guides\n/reference ",
      exclude_paths: " /archive ",
      max_pages: 250,
      max_depth: 4,
    };

    expect(lines(form.additional_hosts)).toEqual([
      "assets.example.com",
      "cdn.example.com",
    ]);
    expect(isUrlSourceFormValid(form)).toBe(true);
    expect(createUrlSourcePayload(form)).toMatchObject({
      additional_hosts: ["assets.example.com", "cdn.example.com"],
      include_paths: ["/guides", "/reference"],
      exclude_paths: ["/archive"],
      max_pages: 1,
      max_depth: 0,
    });
  });

  it("rejects invalid URLs, host exceptions, and paths", () => {
    const valid = {
      ...INITIAL_URL_SOURCE_FORM,
      name: "Docs",
      starting_url: "https://docs.example.com",
    };

    expect(
      isUrlSourceFormValid({ ...valid, starting_url: "ftp://example.com" }),
    ).toBe(false);
    expect(
      isUrlSourceFormValid({ ...valid, additional_hosts: "192.168.1.10" }),
    ).toBe(false);
    expect(isUrlSourceFormValid({ ...valid, include_paths: "docs" })).toBe(
      false,
    );
  });
});
