import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type { Connector } from "@/app/api/queries/useGetConnectorsQuery";
import {
  renderWithProviders,
  screen,
  userEvent,
  waitFor,
} from "@/test-utils/render";
import PluginSettingsDialog from "./plugin-settings-dialog";

const connector: Connector = {
  id: "sharepoint_onprem",
  type: "sharepoint_onprem",
  name: "SharePoint Server",
  description: "On-premises documents",
  icon: "",
  available: true,
  status: "connected",
  connectionId: "existing-id",
  kind: "bucket",
  browseCapability: "hierarchical",
  configFields: [
    { name: "root_url", label: "Root URL", type: "text", required: true },
    { name: "username", label: "Username", type: "secret", required: true },
    { name: "password", label: "Password", type: "secret", required: true },
    { name: "domain", label: "Domain", type: "text", required: true },
    { name: "site_paths", label: "Site paths", type: "text", required: true },
  ],
};

describe("PluginSettingsDialog", () => {
  it("tests credentials without saving, then saves the edited config against the existing connection", async () => {
    const tested: unknown[] = [];
    const saved: unknown[] = [];
    renderWithProviders(
      <PluginSettingsDialog connector={connector} setOpen={() => {}} />,
      {
        providers: ["auth"],
        handlers: [
          http.get("/api/connectors/sharepoint_onprem/plugin-defaults", () =>
            HttpResponse.json({
              connection_id: "existing-id",
              config: {
                root_url: "https://sp.example.org",
                domain: "ACME",
                site_paths: "teams/docs",
              },
              secrets_set: { username: true, password: true },
            }),
          ),
          http.post(
            "/api/connectors/sharepoint_onprem/plugin-test",
            async ({ request }) => {
              tested.push(await request.json());
              return HttpResponse.json({ status: "ok" });
            },
          ),
          http.post(
            "/api/connectors/sharepoint_onprem/plugin-configure",
            async ({ request }) => {
              saved.push(await request.json());
              return HttpResponse.json({
                connection_id: "existing-id",
                status: "connected",
              });
            },
          ),
        ],
      },
    );
    const user = userEvent.setup();
    await user.clear(
      await screen.findByRole("textbox", { name: "Site paths" }),
    );
    await user.type(
      screen.getByRole("textbox", { name: "Site paths" }),
      "teams/docs{enter}teams/plans",
    );
    await user.click(screen.getByRole("button", { name: "Test Connection" }));
    await waitFor(() => expect(tested).toHaveLength(1));
    expect(
      await screen.findByText(
        "Connection tested; save to persist these settings.",
      ),
    ).toBeInTheDocument();
    expect(saved).toHaveLength(0);
    expect(tested[0]).toEqual({
      connection_id: "existing-id",
      config: {
        root_url: "https://sp.example.org",
        domain: "ACME",
        site_paths: "teams/docs\nteams/plans",
      },
    });
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(saved).toEqual(tested));
  });

  it("surfaces validation failures from the remote test without saving", async () => {
    let saves = 0;
    renderWithProviders(
      <PluginSettingsDialog connector={connector} setOpen={() => {}} />,
      {
        providers: ["auth"],
        handlers: [
          http.get("/api/connectors/sharepoint_onprem/plugin-defaults", () =>
            HttpResponse.json({
              connection_id: null,
              config: {},
              secrets_set: {},
            }),
          ),
          http.post("/api/connectors/sharepoint_onprem/plugin-test", () =>
            HttpResponse.json({ error: "Origin not allowed" }, { status: 400 }),
          ),
          http.post(
            "/api/connectors/sharepoint_onprem/plugin-configure",
            () => {
              saves++;
              return HttpResponse.json({});
            },
          ),
        ],
      },
    );
    const user = userEvent.setup();
    await user.type(
      await screen.findByRole("textbox", { name: "Root URL" }),
      "https://blocked.example.org",
    );
    await user.type(screen.getByLabelText("Username"), "alice");
    await user.type(screen.getByLabelText("Password"), "badpassword");
    await user.type(screen.getByRole("textbox", { name: "Domain" }), "ACME");
    await user.type(
      screen.getByRole("textbox", { name: "Site paths" }),
      "teams/docs",
    );
    await user.click(screen.getByRole("button", { name: "Test Connection" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Origin not allowed",
    );
    expect(saves).toBe(0);
  });

  it("requires username and password to be edited together when both are write-only", async () => {
    let requests = 0;
    renderWithProviders(
      <PluginSettingsDialog connector={connector} setOpen={() => {}} />,
      {
        providers: ["auth"],
        handlers: [
          http.get("/api/connectors/sharepoint_onprem/plugin-defaults", () =>
            HttpResponse.json({
              connection_id: "existing-id",
              config: {
                root_url: "https://sp.example.org",
                domain: "ACME",
                site_paths: "teams/docs",
              },
              secrets_set: { username: true, password: true },
            }),
          ),
          http.post("/api/connectors/sharepoint_onprem/plugin-test", () => {
            requests++;
            return HttpResponse.json({ status: "ok" });
          }),
        ],
      },
    );
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Username"), "new-user");
    await user.click(screen.getByRole("button", { name: "Test Connection" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Enter both Username and Password",
    );
    expect(requests).toBe(0);
  });
});
