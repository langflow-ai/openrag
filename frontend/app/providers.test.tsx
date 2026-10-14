import { afterEach, describe, expect, it, vi } from "vitest";

describe("Providers fetch interceptor", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("adds the configured base path to same-origin API fetches", async () => {
    const originalFetch = window.fetch;
    const underlyingFetch = vi
      .fn()
      .mockResolvedValue(new Response("{}", { status: 200 }));

    window.fetch = underlyingFetch as typeof window.fetch;
    vi.stubEnv("NEXT_PUBLIC_OPENRAG_FRONTEND_BASE_PATH", "/openrag-fe");
    vi.resetModules();
    await import("./providers");

    await window.fetch("/api/langflow", { method: "POST" });

    expect(underlyingFetch).toHaveBeenCalledWith("/openrag-fe/api/langflow", {
      method: "POST",
    });

    window.fetch = originalFetch;
  });
});
