import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { makeSettings } from "@/test-utils/fixtures/settings";
import { renderWithProviders } from "@/test-utils/render";
import { ConversationSettingsSection } from "./conversation-settings-section";

describe("ConversationSettingsSection", () => {
  it("renders the toggle as enabled and defaults to the operator TTL when no workspace retention is set", async () => {
    renderWithProviders(<ConversationSettingsSection />, {
      handlers: [
        http.get("/api/settings", () =>
          HttpResponse.json(
            makeSettings({
              conversation_pruning_enabled: true,
              conversation_ttl_days: 90,
              conversation_retention_days: null,
            }),
          ),
        ),
      ],
    });

    await waitFor(() =>
      expect(
        screen.getByRole("switch", {
          name: "Automatically delete inactive conversations",
        }),
      ).toBeChecked(),
    );
    // Selector should show the fallback operator cap value
    expect(
      await screen.findByRole("combobox", { name: "Retention period" }),
    ).toHaveTextContent("90 days");
    expect(
      screen.getByText(
        /are permanently deleted, including their messages and attachments/,
      ),
    ).toBeInTheDocument();
  });

  it("renders the selector with the saved workspace retention days", async () => {
    renderWithProviders(<ConversationSettingsSection />, {
      handlers: [
        http.get("/api/settings", () =>
          HttpResponse.json(
            makeSettings({
              conversation_pruning_enabled: true,
              conversation_ttl_days: 90,
              conversation_retention_days: 30,
            }),
          ),
        ),
      ],
    });

    expect(
      await screen.findByRole("combobox", { name: "Retention period" }),
    ).toHaveTextContent("30 days");
  });

  it("filters out preset options that exceed the operator cap", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ConversationSettingsSection />, {
      handlers: [
        http.get("/api/settings", () =>
          HttpResponse.json(
            makeSettings({
              conversation_pruning_enabled: true,
              conversation_ttl_days: 30,
              conversation_retention_days: 30,
            }),
          ),
        ),
      ],
    });

    const trigger = await screen.findByRole("combobox", {
      name: "Retention period",
    });
    await user.click(trigger);
    const listbox = await screen.findByRole("listbox");
    const options = within(listbox)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toEqual(["7 days", "14 days", "30 days"]);
    // 60 and 90 days must not appear — they exceed the 30-day operator cap
    expect(options).not.toContain("60 days");
    expect(options).not.toContain("90 days");
  });

  it("sends conversation_retention_days to the API when a new option is chosen", async () => {
    const user = userEvent.setup();
    const update = vi.fn();

    renderWithProviders(<ConversationSettingsSection />, {
      handlers: [
        http.get("/api/settings", () =>
          HttpResponse.json(
            makeSettings({
              conversation_pruning_enabled: true,
              conversation_ttl_days: 90,
              conversation_retention_days: 90,
            }),
          ),
        ),
        http.post("/api/settings", async ({ request }) => {
          update(await request.json());
          return HttpResponse.json({
            message: "Configuration updated successfully",
          });
        }),
      ],
    });

    const trigger = await screen.findByRole("combobox", {
      name: "Retention period",
    });
    await user.click(trigger);
    await user.click(await screen.findByRole("option", { name: "30 days" }));

    await waitFor(() => {
      expect(update).toHaveBeenCalledWith({ conversation_retention_days: 30 });
    });
  });

  it("sends conversation_pruning_enabled=false when the toggle is turned off", async () => {
    const user = userEvent.setup();
    const update = vi.fn();

    renderWithProviders(<ConversationSettingsSection />, {
      handlers: [
        http.get("/api/settings", () =>
          HttpResponse.json(
            makeSettings({
              conversation_pruning_enabled: true,
              conversation_ttl_days: 90,
              conversation_retention_days: 90,
            }),
          ),
        ),
        http.post("/api/settings", async ({ request }) => {
          update(await request.json());
          return HttpResponse.json({
            message: "Configuration updated successfully",
          });
        }),
        http.post("/api/models/openai", () =>
          HttpResponse.json({ models: [] }),
        ),
      ],
    });

    const toggle = await screen.findByRole("switch", {
      name: "Automatically delete inactive conversations",
    });
    await waitFor(() => expect(toggle).toBeChecked());
    await user.click(toggle);

    await waitFor(() => {
      expect(update).toHaveBeenCalledWith({
        conversation_pruning_enabled: false,
      });
    });
  });

  it("disables the selector when pruning is toggled off", async () => {
    renderWithProviders(<ConversationSettingsSection />, {
      handlers: [
        http.get("/api/settings", () =>
          HttpResponse.json(
            makeSettings({
              conversation_pruning_enabled: false,
              conversation_ttl_days: 90,
              conversation_retention_days: 90,
            }),
          ),
        ),
      ],
    });

    const trigger = await screen.findByRole("combobox", {
      name: "Retention period",
    });
    expect(trigger).toBeDisabled();
  });

  it("shows the disabled message and hides the selector when pruning is globally disabled", async () => {
    renderWithProviders(<ConversationSettingsSection />, {
      handlers: [
        http.get("/api/settings", () =>
          HttpResponse.json(
            makeSettings({
              conversation_pruning_enabled: true,
              conversation_ttl_days: null,
            }),
          ),
        ),
      ],
    });

    await screen.findByText("Disabled by the deployment administrator.");
    expect(
      screen.queryByRole("combobox", { name: "Retention period" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("switch", {
        name: "Automatically delete inactive conversations",
      }),
    ).toBeDisabled();
  });
});
