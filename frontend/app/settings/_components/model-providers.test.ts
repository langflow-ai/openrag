import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("providerDialogCloseUrl", () => {
  it("removes the frontend base path before returning a router URL", async () => {
    vi.stubEnv("NEXT_PUBLIC_OPENRAG_FRONTEND_BASE_PATH", "/openrag-fe");
    const { providerDialogCloseUrl } = await import("./model-providers");

    expect(
      providerDialogCloseUrl(
        "/openrag-fe/settings/providers",
        new URLSearchParams("tab=all"),
      ),
    ).toBe("/settings/providers?tab=all");
  });
});
