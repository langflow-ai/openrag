import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { makeSettings } from "@/test-utils/fixtures/settings";
import { renderWithProviders } from "@/test-utils/render";
import { ConversationSettingsSection } from "./conversation-settings-section";

describe("ConversationSettingsSection", () => {
  it("updates the optional pruning setting", async () => {
    const user = userEvent.setup();
    const update = vi.fn();

    renderWithProviders(<ConversationSettingsSection />, {
      handlers: [
        http.get("/api/settings", () =>
          HttpResponse.json(
            makeSettings({
              conversation_pruning_enabled: true,
              conversation_ttl_days: 90,
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
      name: "Automatically delete stale conversations",
    });
    await waitFor(() => expect(toggle).toBeChecked());
    expect(
      screen.getByText(
        "Conversations inactive for more than 90 days are deleted nightly.",
      ),
    ).toBeInTheDocument();

    await user.click(toggle);

    await waitFor(() => {
      expect(update).toHaveBeenCalledWith({
        conversation_pruning_enabled: false,
      });
    });
  });

  it("disables the toggle when pruning is disabled deployment-wide", async () => {
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
      screen.getByRole("switch", {
        name: "Automatically delete stale conversations",
      }),
    ).toBeDisabled();
  });
});
