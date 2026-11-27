import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import { makeSettings } from "@/test-utils/fixtures/settings";
import { renderWithProviders, screen, waitFor } from "@/test-utils/render";
import { SettingsNav } from "./settings-nav";

vi.mock("@/contexts/brand-context", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/contexts/brand-context")>()),
  useIsCloudBrand: () => false,
}));
vi.mock("@/hooks/use-permissions", () => ({
  useSettingsTabAccess: () => ({
    "config:write": true,
    "providers:write": true,
    "connectors:manage:access": true,
  }),
}));

describe("SettingsNav", () => {
  it("hides Advanced when Langflow is deployment-disabled", async () => {
    renderWithProviders(<SettingsNav />, {
      providers: ["auth"],
      auth: authPresets.admin,
      handlers: [
        http.get("/api/settings", () =>
          HttpResponse.json(makeSettings({ langflow_configurable: false })),
        ),
      ],
    });

    await waitFor(() => {
      expect(screen.queryByRole("tab", { name: "Advanced" })).toBeNull();
    });
  });

  it("keeps Advanced visible for configurable and older deployments", async () => {
    renderWithProviders(<SettingsNav />, {
      providers: ["auth"],
      auth: authPresets.admin,
      handlers: [
        http.get("/api/settings", () => HttpResponse.json(makeSettings())),
      ],
    });

    expect(
      await screen.findByRole("tab", { name: "Advanced" }),
    ).toBeInTheDocument();
  });
});
