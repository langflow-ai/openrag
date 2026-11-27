import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import { makeSettings } from "@/test-utils/fixtures/settings";
import { renderWithProviders, screen, waitFor } from "@/test-utils/render";
import { LangflowUpdatesBanner } from "./langflow-updates-banner";

describe("LangflowUpdatesBanner", () => {
  it("does not fetch or display flow updates while Langflow is disabled", async () => {
    let settingsRequested = false;

    renderWithProviders(<LangflowUpdatesBanner />, {
      providers: ["brand"],
      auth: authPresets.admin,
      handlers: [
        http.get("/api/settings", () => {
          settingsRequested = true;
          return HttpResponse.json(makeSettings({ langflow_enabled: false }));
        }),
      ],
    });

    await waitFor(() => expect(settingsRequested).toBe(true));
    expect(
      screen.queryByText("Langflow flow updates available"),
    ).not.toBeInTheDocument();
  });
});
