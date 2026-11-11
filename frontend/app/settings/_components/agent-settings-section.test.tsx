import { fireEvent, screen, waitFor } from "@testing-library/react";
import { HttpResponse, http } from "msw";
import { describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { authPresets } from "@/test-utils/fixtures/auth";
import { makeSettings } from "@/test-utils/fixtures/settings";
import { renderWithProviders } from "@/test-utils/render";
import { AgentSettingsSection } from "./agent-settings-section";

vi.mock("@/lib/analytics", () => ({ trackButton: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function handlers(nativeChatAvailable = false) {
  return [
    http.get("/api/settings", () =>
      HttpResponse.json(
        makeSettings({
          agent: {
            system_prompt: "Be helpful.",
            default_system_prompt: "Default instructions.",
            native_chat_available: nativeChatAvailable,
          },
        }),
      ),
    ),
    http.get("/api/models/catalog", () => HttpResponse.json({ providers: [] })),
    http.get("/api/models/providers", () => HttpResponse.json({})),
  ];
}

function renderSection(nativeChatAvailable = false) {
  return renderWithProviders(<AgentSettingsSection />, {
    providers: ["tooltip", "auth", "brand", "unsavedChanges"],
    auth: authPresets.admin,
    handlers: handlers(nativeChatAvailable),
  });
}

describe("AgentSettingsSection", () => {
  it("updates the system prompt as the user types", async () => {
    renderSection();

    const textarea = await screen.findByPlaceholderText(
      "Enter your agent instructions here...",
    );
    await waitFor(() => expect(textarea).toHaveValue("Be helpful."));

    fireEvent.change(textarea, { target: { value: "Be very helpful." } });
    expect(textarea).toHaveValue("Be very helpful.");
  });

  it("restores the default system prompt when 'Restore default' is clicked", async () => {
    renderSection();

    const textarea = await screen.findByPlaceholderText(
      "Enter your agent instructions here...",
    );
    await waitFor(() => expect(textarea).toHaveValue("Be helpful."));

    fireEvent.click(
      await screen.findByRole("button", { name: /restore default/i }),
    );
    expect(textarea).toHaveValue("Default instructions.");
  });

  it("updates the Langflow chat switch when native chat is available", async () => {
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({
      status: 200,
      data: { message: "Settings updated", settings: {} },
    } as never);
    renderSection(true);

    fireEvent.click(
      await screen.findByRole("switch", { name: /disable langflow chat/i }),
    );

    await waitFor(() => {
      expect(post).toHaveBeenCalledWith("/settings", {
        disable_chat_with_langflow: true,
      });
    });
  });
});
