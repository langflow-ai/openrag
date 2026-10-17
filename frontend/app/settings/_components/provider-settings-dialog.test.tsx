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
    // A changed TLS setting is a new credential target: the saved key is not
    // reused, so it has to be typed again.
    await user.type(screen.getByLabelText(/^API key/), "new-key");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(submitted).toEqual({
        provider_credentials: {
          watsonx_onprem: {
            api_base: "https://cpd.example.com",
            username: "cpd-user",
            api_key: "new-key",
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

const SAVED_HINT = "A value is already saved. Leave this blank to keep it.";
const REENTRY_HINT =
  "The endpoint or TLS setting changed, so the saved value is not sent to it. Enter it again.";

const azureCatalog = {
  providers: [
    {
      key: "azure",
      name: "Azure OpenAI",
      credential_fields: [
        {
          key: "api_base",
          label: "Endpoint",
          required: true,
          field_type: "text",
        },
        {
          key: "api_key",
          label: "API key",
          required: false,
          field_type: "password",
        },
        {
          key: "azure_ad_token",
          label: "Access token",
          required: false,
          field_type: "password",
        },
        {
          key: "api_version",
          label: "API version",
          required: false,
          field_type: "text",
        },
      ],
      models: [],
      embedding_models: [],
    },
  ],
};

function renderDialog({
  provider,
  providerCatalog,
  credentialValues,
  secretFields,
  authMethod,
}: {
  provider: string;
  providerCatalog: typeof catalog;
  credentialValues: Record<string, string>;
  secretFields: string[];
  authMethod: string;
}) {
  const result: {
    submitted?: UpdateSettingsRequest;
    discoveryRequests: number;
  } = { discoveryRequests: 0 };
  const settings = makeSettings({
    providers: {
      custom: {
        [provider]: {
          configured: true,
          auth_method: authMethod,
          credential_values: credentialValues,
          secret_fields: secretFields,
        },
      },
    },
  });

  renderWithProviders(
    <ProviderSettingsDialog
      provider={provider}
      displayName={provider}
      open
      setOpen={() => {}}
    />,
    {
      providers: ["auth", "tooltip"],
      handlers: [
        http.get("/api/settings", () => HttpResponse.json(settings)),
        http.get("/api/models/catalog", () =>
          HttpResponse.json(providerCatalog),
        ),
        http.post("/api/models/watsonx_onprem/spaces", () => {
          result.discoveryRequests += 1;
          return HttpResponse.json({ spaces: [] });
        }),
        http.post("/api/settings", async ({ request }) => {
          result.submitted = (await request.json()) as UpdateSettingsRequest;
          return HttpResponse.json({ message: "saved", settings });
        }),
        http.post("/api/models/openai", () =>
          HttpResponse.json({ models: [], embedding_models: [] }),
        ),
      ],
    },
  );
  return result;
}

const onPremSaved = {
  provider: "watsonx_onprem",
  providerCatalog: catalog,
  credentialValues: {
    api_base: "https://cpd.example.com",
    username: "cpd-user",
    ssl_verify: "true",
  },
  secretFields: ["api_key"],
  authMethod: "username_api_key",
};

describe("ProviderSettingsDialog credential target changes", () => {
  it("offers to keep a saved secret while the target is unchanged", async () => {
    renderDialog(onPremSaved);

    expect(await screen.findByText(SAVED_HINT)).toBeInTheDocument();
    expect(screen.queryByText(REENTRY_HINT)).not.toBeInTheDocument();
  });

  it("requires the saved secret again once the endpoint changes", async () => {
    const result = renderDialog(onPremSaved);
    const user = userEvent.setup();

    const endpoint = await screen.findByLabelText(/^Cluster URL/);
    await screen.findByText(SAVED_HINT);
    await user.clear(endpoint);
    await user.type(endpoint, "https://other.example.com");

    expect(screen.queryByText(SAVED_HINT)).not.toBeInTheDocument();
    expect(screen.getByText(REENTRY_HINT)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("API key is required")).toBeInTheDocument();
    expect(result.submitted).toBeUndefined();
  });

  it("saves the new endpoint once the secret is typed again", async () => {
    const result = renderDialog(onPremSaved);
    const user = userEvent.setup();

    const endpoint = await screen.findByLabelText(/^Cluster URL/);
    await screen.findByText(SAVED_HINT);
    await user.clear(endpoint);
    await user.type(endpoint, "https://other.example.com");
    await user.type(screen.getByLabelText(/^API key/), "new-key");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(result.submitted?.provider_credentials?.watsonx_onprem).toEqual({
        api_base: "https://other.example.com",
        username: "cpd-user",
        api_key: "new-key",
        ssl_verify: "true",
      });
    });
  });

  it("treats a cleared endpoint as a target change", async () => {
    const result = renderDialog(onPremSaved);
    const user = userEvent.setup();

    const endpoint = await screen.findByLabelText(/^Cluster URL/);
    await screen.findByText(SAVED_HINT);
    await user.clear(endpoint);

    expect(screen.getByText(REENTRY_HINT)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("API key is required")).toBeInTheDocument();
    expect(result.submitted).toBeUndefined();
  });

  it("does not list deployment spaces with a key saved for another endpoint", async () => {
    const result = renderDialog(onPremSaved);
    const user = userEvent.setup();

    const endpoint = await screen.findByLabelText(/^Cluster URL/);
    await user.click(screen.getByRole("button", { name: "Advanced settings" }));
    const spaceSelect = screen.getByRole("combobox", {
      name: "Deployment space ID",
    });
    await waitFor(() => expect(spaceSelect).not.toBeDisabled());
    const requestsBeforeEdit = result.discoveryRequests;

    await user.clear(endpoint);
    await user.type(endpoint, "https://other.example.com");

    await waitFor(() => expect(spaceSelect).toBeDisabled());
    expect(result.discoveryRequests).toBe(requestsBeforeEdit);
  });

  it("does not demand a saved secret of an auth method that is not chosen", async () => {
    const result = renderDialog({
      provider: "azure",
      providerCatalog: azureCatalog,
      credentialValues: { api_base: "https://old.openai.azure.com" },
      secretFields: ["api_key"],
      authMethod: "api_key",
    });
    const user = userEvent.setup();

    const endpoint = await screen.findByLabelText(/^Endpoint/);
    await screen.findByText(SAVED_HINT);
    await user.click(
      screen.getByRole("button", { name: "Microsoft Entra access token" }),
    );
    await user.clear(endpoint);
    await user.type(endpoint, "https://new.openai.azure.com");
    await user.type(screen.getByLabelText(/^Access token/), "entra-token");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(result.submitted).toEqual({
        provider_credentials: {
          azure: {
            api_base: "https://new.openai.azure.com",
            azure_ad_token: "entra-token",
          },
        },
        provider_auth_methods: { azure: "entra_token" },
      });
    });
  });

  it("requires the chosen auth method's saved secret after the endpoint changes", async () => {
    const result = renderDialog({
      provider: "azure",
      providerCatalog: azureCatalog,
      credentialValues: { api_base: "https://old.openai.azure.com" },
      secretFields: ["api_key"],
      authMethod: "api_key",
    });
    const user = userEvent.setup();

    const endpoint = await screen.findByLabelText(/^Endpoint/);
    await screen.findByText(SAVED_HINT);
    await user.clear(endpoint);
    await user.type(endpoint, "https://new.openai.azure.com");

    expect(screen.getByText(REENTRY_HINT)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("API key is required")).toBeInTheDocument();
    expect(result.submitted).toBeUndefined();
  });
});
