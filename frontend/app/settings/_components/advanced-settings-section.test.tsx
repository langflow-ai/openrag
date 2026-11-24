import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import { makeSettings } from "@/test-utils/fixtures/settings";
import {
  renderWithProviders,
  screen,
  userEvent,
  waitFor,
} from "@/test-utils/render";
import { AdvancedSettingsSection } from "./advanced-settings-section";

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

describe("AdvancedSettingsSection", () => {
  it("shows the master toggle when an older backend omits the capability field", async () => {
    renderWithProviders(<AdvancedSettingsSection />, {
      providers: ["auth"],
      auth: authPresets.admin,
      handlers: [
        http.get("/api/settings", () => HttpResponse.json(makeSettings())),
      ],
    });

    expect(
      await screen.findByRole("switch", { name: /disable langflow/i }),
    ).toBeInTheDocument();
  });

  it("does not expose the application toggle when deployment disables Langflow", async () => {
    let loaded = false;
    renderWithProviders(<AdvancedSettingsSection />, {
      providers: ["auth"],
      auth: authPresets.admin,
      handlers: [
        http.get("/api/settings", () => {
          loaded = true;
          return HttpResponse.json(
            makeSettings({ langflow_configurable: false }),
          );
        }),
      ],
    });

    await waitFor(() => expect(loaded).toBe(true));
    expect(
      screen.queryByRole("switch", { name: /disable langflow/i }),
    ).toBeNull();
  });

  it("saves the master disable choice", async () => {
    let requestBody: unknown;
    renderWithProviders(<AdvancedSettingsSection />, {
      providers: ["auth"],
      auth: authPresets.admin,
      handlers: [
        http.get("/api/settings", () =>
          HttpResponse.json(
            makeSettings({
              langflow_configurable: true,
              langflow_enabled: true,
            }),
          ),
        ),
        http.post("/api/settings", async ({ request }) => {
          requestBody = await request.json();
          return HttpResponse.json({ success: true });
        }),
      ],
    });

    await userEvent.click(
      await screen.findByRole("switch", { name: /disable langflow/i }),
    );

    await waitFor(() => {
      expect(requestBody).toEqual({ disable_langflow: true });
    });
  });
});
