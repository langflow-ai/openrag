import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import { makeSettings } from "@/test-utils/fixtures/settings";
import { renderWithProviders } from "@/test-utils/render";
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
        http.get("/api/connectors/url/sources", () =>
          HttpResponse.json({ sources: [] }),
        ),
      ],
    });

    expect(await screen.findByText("Built-in Connectors")).toBeVisible();
    expect(screen.getByText("URL is connected.")).toBeVisible();

    await user.click(screen.getByRole("button", { name: /add knowledge/i }));

    expect(
      await screen.findByRole("heading", { name: "Add a Website connection" }),
    ).toBeVisible();
  });
});

describe("runtime connector catalog", () => {
  it("offers configuration for an allowlisted connector without a frontend registry entry", async () => {
    renderWithProviders(<ConnectorCards />, {
      providers: ["auth", "brand", "tooltip"],
      auth: authPresets.rbacDisabled,
      handlers: [
        http.get("/api/connectors", () =>
          HttpResponse.json({
            connectors: {
              sharepoint_onprem: {
                name: "SharePoint Server",
                description: "Browse your private SharePoint Server",
                icon: "",
                kind: "bucket",
                available: true,
                browse_capability: "hierarchical",
                config_fields: [
                  {
                    name: "root_url",
                    label: "Root URL",
                    type: "text",
                    required: true,
                  },
                  {
                    name: "username",
                    label: "Username",
                    type: "text",
                    required: true,
                  },
                ],
              },
            },
          }),
        ),
        http.get("/api/connectors/sharepoint_onprem/status", () =>
          HttpResponse.json({ connections: [] }),
        ),
        http.get("/api/connectors/sharepoint_onprem/plugin-defaults", () =>
          HttpResponse.json({
            connection_id: null,
            config: {},
            secrets_set: {},
          }),
        ),
      ],
    });
    expect(
      await screen.findByText("Browse your private SharePoint Server"),
    ).toBeInTheDocument();
    await userEvent
      .setup()
      .click(await screen.findByRole("button", { name: "Configure" }));
    expect(
      await screen.findByRole("dialog", {
        name: "Configure SharePoint Server",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("textbox", { name: "Root URL" }),
    ).toBeInTheDocument();
  });

  it("shows the built-in icon a plugin names instead of the unknown placeholder", async () => {
    renderWithProviders(<ConnectorCards />, {
      providers: ["auth", "brand", "tooltip"],
      auth: authPresets.rbacDisabled,
      handlers: [
        http.get("/api/connectors", () =>
          HttpResponse.json({
            connectors: {
              sharepoint_onprem: {
                name: "SharePoint Server",
                description: "Browse your private SharePoint Server",
                icon: "sharepoint",
                kind: "bucket",
                available: true,
                browse_capability: "hierarchical",
                config_fields: [],
              },
            },
          }),
        ),
        http.get("/api/connectors/sharepoint_onprem/status", () =>
          HttpResponse.json({ connections: [] }),
        ),
      ],
    });
    expect(
      await screen.findByText("Browse your private SharePoint Server"),
    ).toBeInTheDocument();
    expect(screen.queryByText("?")).not.toBeInTheDocument();
  });
});
