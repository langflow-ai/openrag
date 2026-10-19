import {
  PHASE_DEVELOPMENT_SERVER,
  PHASE_PRODUCTION_BUILD,
} from "next/constants";
import { afterEach, describe, expect, it, vi } from "vitest";
import createNextConfig from "./next.config";

describe("next configuration base path", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it.each([
    ["", ""],
    ["/", ""],
    [" openrag-fe/ ", "/openrag-fe"],
  ])("normalizes production base path %j to %j", (path, expected) => {
    vi.stubEnv("OPENRAG_FRONTEND_BASE_PATH", path);
    vi.stubEnv("OPENRAG_FRONTEND_RUNTIME_BASE_PATH", "");

    expect(createNextConfig(PHASE_PRODUCTION_BUILD).basePath).toBe(expected);
  });

  it("rejects paths that would route differently in the browser", () => {
    vi.stubEnv("OPENRAG_FRONTEND_BASE_PATH", "/a/../b");
    vi.stubEnv("OPENRAG_FRONTEND_RUNTIME_BASE_PATH", "");

    expect(() => createNextConfig(PHASE_PRODUCTION_BUILD)).toThrow(
      "OPENRAG_FRONTEND_BASE_PATH",
    );
  });

  it("uses the configured path for a local production build", () => {
    vi.stubEnv("OPENRAG_FRONTEND_BASE_PATH", "/openrag-fe");
    vi.stubEnv("OPENRAG_FRONTEND_RUNTIME_BASE_PATH", "");

    expect(createNextConfig(PHASE_PRODUCTION_BUILD).basePath).toBe(
      "/openrag-fe",
    );
  });

  it("uses the placeholder only when building the container image", () => {
    vi.stubEnv("OPENRAG_FRONTEND_BASE_PATH", "/openrag-fe");
    vi.stubEnv("OPENRAG_FRONTEND_RUNTIME_BASE_PATH", "true");

    expect(createNextConfig(PHASE_PRODUCTION_BUILD).basePath).toBe(
      "/NEXT_PUBLIC_BASE_PATH_PLACEHOLDER_a1b2c3d4",
    );
  });

  it("keeps next dev configurable even when the image-build flag is set", () => {
    vi.stubEnv("OPENRAG_FRONTEND_BASE_PATH", "/openrag-fe");
    vi.stubEnv("OPENRAG_FRONTEND_RUNTIME_BASE_PATH", "true");

    expect(createNextConfig(PHASE_DEVELOPMENT_SERVER).basePath).toBe(
      "/openrag-fe",
    );
  });
});
