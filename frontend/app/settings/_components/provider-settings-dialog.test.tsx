import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import type { UpdateSettingsRequest } from "@/app/api/mutations/useUpdateSettingsMutation";
import { makeSettings } from "@/test-utils/fixtures/settings";
import {
  renderWithProviders,
  screen,
  userEvent,
  waitFor,
} from "@/test-utils/render";
import ProviderSettingsDialog from "./provider-settings-dialog";

const catalog = {
  providers: [
    {
      key: "watsonx_onprem",
      name: "IBM watsonx.ai",
      credential_fields: [
        {
          key: "api_base",
          label: "Cluster URL",
          required: true,
          field_type: "text",
        },
        {
          key: "username",
          label: "Username",
          required: true,
          field_type: "text",
        },
        {
          key: "api_key",
          label: "API key",
          required: true,
          field_type: "password",
        },
        {
          key: "space_id",
          label: "Deployment space ID",
          required: false,
          field_type: "text",
        },
        {
          key: "ssl_verify",
          label: "TLS certificate verification",
          required: false,
          field_type: "text",
        },
      ],
      models: [],
      embedding_models: [],
    },
  ],
};

describe("ProviderSettingsDialog watsonx.ai on-prem TLS", () => {
  it("submits the advanced TLS policy with only the on-prem provider", async () => {
    let submitted: UpdateSettingsRequest | undefined;
    const settings = makeSettings({
      providers: {
        custom: {
          watsonx_onprem: {
            configured: true,
            auth_method: "username_api_key",
            credential_values: {
              api_base: "https://cpd.example.com",
              username: "cpd-user",
              ssl_verify: "true",
            },
            secret_fields: ["api_key"],
          },
        },
      },
    });

    renderWithProviders(
      <ProviderSettingsDialog
        provider="watsonx_onprem"
        displayName="IBM watsonx.ai (on-prem)"
        open
        setOpen={() => {}}
      />,
      {
        providers: ["auth", "tooltip"],
        handlers: [
          http.get("/api/settings", () => HttpResponse.json(settings)),
          http.get("/api/models/catalog", () => HttpResponse.json(catalog)),
          http.post("/api/models/watsonx_onprem/spaces", () =>
            HttpResponse.json({ spaces: [] }),
          ),
          http.post("/api/settings", async ({ request }) => {
            submitted = (await request.json()) as UpdateSettingsRequest;
            return HttpResponse.json({ message: "saved", settings });
          }),
          http.post("/api/models/openai", () =>
            HttpResponse.json({ models: [], embedding_models: [] }),
          ),
        ],
      },
    );

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Advanced settings" }),
    );
    await user.click(
      screen.getByRole("switch", { name: "Verify TLS certificates" }),
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(submitted).toEqual({
        provider_credentials: {
          watsonx_onprem: {
            api_base: "https://cpd.example.com",
            username: "cpd-user",
            ssl_verify: "false",
          },
        },
        provider_auth_methods: { watsonx_onprem: "username_api_key" },
      });
    });
  });

  it("submits a cleared optional field so the backend can remove it", async () => {
    let submitted: UpdateSettingsRequest | undefined;
    const settings = makeSettings({
      providers: {
        custom: {
          watsonx_onprem: {
            configured: true,
            auth_method: "username_api_key",
            credential_values: {
              api_base: "https://cpd.example.com",
              username: "cpd-user",
              space_id: "deployment-space",
              ssl_verify: "true",
            },
            secret_fields: ["api_key"],
          },
        },
      },
    });

    renderWithProviders(
      <ProviderSettingsDialog
        provider="watsonx_onprem"
        displayName="IBM watsonx.ai (on-prem)"
        open
        setOpen={() => {}}
      />,
      {
        providers: ["auth", "tooltip"],
        handlers: [
          http.get("/api/settings", () => HttpResponse.json(settings)),
          http.get("/api/models/catalog", () => HttpResponse.json(catalog)),
          http.post("/api/models/watsonx_onprem/spaces", () =>
            HttpResponse.json({ spaces: [] }),
          ),
          http.post("/api/settings", async ({ request }) => {
            submitted = (await request.json()) as UpdateSettingsRequest;
            return HttpResponse.json({ message: "saved", settings });
          }),
          http.post("/api/models/openai", () =>
            HttpResponse.json({ models: [], embedding_models: [] }),
          ),
        ],
      },
    );

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Advanced settings" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Clear deployment space" }),
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(submitted?.provider_credentials?.watsonx_onprem).toEqual({
        api_base: "https://cpd.example.com",
        username: "cpd-user",
        ssl_verify: "true",
      });
      expect(submitted?.provider_credential_removals?.watsonx_onprem).toEqual([
        "space_id",
      ]);
    });
  });

  it("loads deployment spaces and submits the selected space", async () => {
    let submitted: UpdateSettingsRequest | undefined;
    let discoveryRequest: unknown;
    const settings = makeSettings({
      providers: {
        custom: {
          watsonx_onprem: {
            configured: true,
            auth_method: "username_api_key",
            credential_values: {
              api_base: "https://cpd.example.com",
              username: "cpd-user",
              ssl_verify: "true",
            },
            secret_fields: ["api_key"],
          },
        },
      },
    });

    renderWithProviders(
      <ProviderSettingsDialog
        provider="watsonx_onprem"
        displayName="IBM watsonx.ai (on-prem)"
        open
        setOpen={() => {}}
      />,
      {
        providers: ["auth", "tooltip"],
        handlers: [
          http.get("/api/settings", () => HttpResponse.json(settings)),
          http.get("/api/models/catalog", () => HttpResponse.json(catalog)),
          http.post(
            "/api/models/watsonx_onprem/spaces",
            async ({ request }) => {
              discoveryRequest = await request.json();
              return HttpResponse.json({
                spaces: [
                  { id: "space-prod", name: "Production" },
                  { id: "space-dev", name: "Development" },
                ],
              });
            },
          ),
          http.post("/api/settings", async ({ request }) => {
            submitted = (await request.json()) as UpdateSettingsRequest;
            return HttpResponse.json({ message: "saved", settings });
          }),
          http.post("/api/models/openai", () =>
            HttpResponse.json({ models: [], embedding_models: [] }),
          ),
        ],
      },
    );

    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Advanced settings" }),
    );
    const spaceSelect = screen.getByRole("combobox", {
      name: "Deployment space ID",
    });
    await waitFor(() => expect(spaceSelect).not.toBeDisabled());
    await user.click(spaceSelect);
    await user.click(
      await screen.findByRole("option", { name: /Production.*space-prod/ }),
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(discoveryRequest).toEqual({
        credentials: {
          api_base: "https://cpd.example.com",
          username: "cpd-user",
          ssl_verify: "true",
        },
        auth_method: "username_api_key",
      });
      expect(submitted?.provider_credentials?.watsonx_onprem?.space_id).toBe(
        "space-prod",
      );
    });
  });
});
