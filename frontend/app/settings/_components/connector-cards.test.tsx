import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import { makeSettings } from "@/test-utils/fixtures/settings";
import { renderWithProviders } from "@/test-utils/render";
import { mockRouter } from "@/test-utils/router";
import ConnectorCards from "./connector-cards";

describe("ConnectorCards", () => {
  it("shows the enabled managed URL connector and opens URL ingestion from its card", async () => {
    const user = userEvent.setup();
    renderWithProviders(<ConnectorCards />, {
      providers: ["brand"],
      auth: authPresets.noAuthMode,
      handlers: [
        http.get("/api/settings", () =>
          HttpResponse.json(makeSettings({ show_url_connector: true })),
        ),
        http.get("/api/connectors", () =>
          HttpResponse.json({
            connectors: {
              url: {
                name: "URL",
                description: "Crawl public websites",
                icon: "url",
                kind: "managed",
                always_connected: true,
                available: true,
              },
            },
          }),
        ),
        http.get("/api/connectors/url/status", () =>
          HttpResponse.json({ connections: [] }),
        ),
      ],
    });

    expect(await screen.findByText("Built-in Connectors")).toBeVisible();
    expect(screen.getByText("URL is connected.")).toBeVisible();

    await user.click(screen.getByRole("button", { name: /add knowledge/i }));

    expect(mockRouter.push).toHaveBeenCalledWith("/knowledge?add=url");
  });
});
