import { describe, expect, it } from "vitest";
import { normalizeFrontendBasePath } from "./frontend-base-path";

describe("normalizeFrontendBasePath", () => {
  it.each([
    [undefined, ""],
    ["", ""],
    ["/", ""],
    ["openrag-fe", "/openrag-fe"],
    [" /openrag-fe/ ", "/openrag-fe"],
    ["/platform/openrag-fe///", "/platform/openrag-fe"],
  ])("normalizes %j to %j", (value, expected) => {
    expect(normalizeFrontendBasePath(value)).toBe(expected);
  });

  it.each([
    "https://example.com/openrag-fe",
    "/openrag-fe?tab=1",
    "/x#y",
  ])("rejects a URL rather than a path (%s)", (value) => {
    expect(() => normalizeFrontendBasePath(value)).toThrow(
      "OPENRAG_FRONTEND_BASE_PATH",
    );
  });
});
