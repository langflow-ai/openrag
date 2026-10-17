import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { authPresets } from "@/test-utils/fixtures/auth";
import { renderWithProviders, screen, userEvent } from "@/test-utils/render";
import ConnectorCards from "./connector-cards";

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
});
