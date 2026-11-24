import { delay, HttpResponse, http } from "msw";
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

const toast = vi.hoisted(() => ({ success: vi.fn(), error: vi.fn() }));

vi.mock("sonner", () => ({ toast }));

describe("AdvancedSettingsSection", () => {
  it("shows an accessible loading state while settings load", async () => {
    renderWithProviders(<AdvancedSettingsSection />, {
      providers: ["auth"],
      auth: authPresets.admin,
      handlers: [
        http.get("/api/settings", async () => {
          await delay("infinite");
          return HttpResponse.json(makeSettings());
        }),
      ],
    });

    expect(
      await screen.findByRole("status", { name: "Loading advanced settings" }),
    ).toBeInTheDocument();
  });

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
    toast.success.mockClear();
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
      expect(toast.success).toHaveBeenCalledWith("Advanced settings updated");
    });
  });

  it("shows the API error when saving the choice fails", async () => {
    toast.error.mockClear();
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
        http.post("/api/settings", () =>
          HttpResponse.json({ error: "Sync unavailable" }, { status: 503 }),
        ),
      ],
    });

    await userEvent.click(
      await screen.findByRole("switch", { name: /disable langflow/i }),
    );

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "Failed to update advanced settings",
        expect.objectContaining({ description: "Sync unavailable" }),
      );
    });
  });
});
