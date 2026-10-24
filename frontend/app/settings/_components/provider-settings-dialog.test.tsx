import { HttpResponse, http } from "msw";
import { useState } from "react";
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
          key: "project_id",
          label: "Project ID",
          required: false,
          field_type: "text",
        },
        {
          key: "ssl_verify",
          label: "Verify TLS certificates",
          required: false,
          field_type: "tls_verify",
        },
      ],
      models: [],
      embedding_models: [],
    },
  ],
};

const ProviderDialogHarness = () => {
  const [open, setOpen] = useState(true);
  return (
    <ProviderSettingsDialog
      provider="watsonx_onprem"
      displayName="IBM watsonx.ai (on-prem)"
      open={open}
      setOpen={setOpen}
    />
  );
};

describe("ProviderSettingsDialog watsonx.ai on-prem TLS", () => {
  it("shows TLS verification before the deployment scope fields", async () => {
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

    const tlsToggle = screen.getByRole("switch", {
      name: "Verify TLS certificates",
    });
    const deploymentSpace = screen.getByRole("combobox", {
      name: "Deployment space ID",
    });
    const projectId = screen.getByRole("textbox", { name: "Project ID" });

    expect(
      tlsToggle.compareDocumentPosition(deploymentSpace) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      deploymentSpace.compareDocumentPosition(projectId) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      tlsToggle.compareDocumentPosition(projectId) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

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
  it("requires explicit confirmation when embedding usage cannot be determined", async () => {
    const submissions: UpdateSettingsRequest[] = [];
    const settings = makeSettings({
      providers: {
        openai: { configured: true },
        custom: {
          watsonx_onprem: {
            configured: true,
            auth_method: "username_api_key",
            credential_values: {
              api_base: "https://cpd.example.com",
              username: "cpd-user",
            },
            secret_fields: ["api_key"],
          },
        },
      },
    });

    renderWithProviders(<ProviderDialogHarness />, {
      providers: ["auth", "tooltip"],
      handlers: [
        http.get("/api/settings", () => HttpResponse.json(settings)),
        http.get("/api/models/catalog", () => HttpResponse.json(catalog)),
        http.post("/api/models/watsonx_onprem/spaces", () =>
          HttpResponse.json({ spaces: [] }),
        ),
        http.post("/api/settings", async ({ request }) => {
          const submission = (await request.json()) as UpdateSettingsRequest;
          submissions.push(submission);
          if (!submission.force_remove) {
            return HttpResponse.json(
              {
                error:
                  "Could not verify whether indexed documents depend on IBM watsonx.ai.",
                code: "embedding_usage_unknown",
                affected_provider: "watsonx_onprem",
                unresolved_legacy_models: ["shared-model"],
              },
              { status: 503 },
            );
          }
          return HttpResponse.json({ message: "saved", settings });
        }),
        http.post("/api/models/openai", () =>
          HttpResponse.json({ models: [], embedding_models: [] }),
        ),
      ],
    });

    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Remove" }));
    await user.click(screen.getByRole("button", { name: "Remove" }));

    expect(
      await screen.findByText(
        /Could not verify whether indexed documents use this provider/,
      ),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Remove" }));
    await user.click(screen.getByRole("button", { name: "Remove" }));
    await screen.findByText(
      /Could not verify whether indexed documents use this provider/,
    );

    await user.click(
      await screen.findByRole("button", { name: /Remove anyway/i }),
    );

    await waitFor(() => {
      expect(submissions).toEqual([
        {
          remove_provider_config: "watsonx_onprem",
          force_remove: false,
        },
        {
          remove_provider_config: "watsonx_onprem",
          force_remove: false,
        },
        {
          remove_provider_config: "watsonx_onprem",
          force_remove: true,
        },
      ]);
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

const rhoaiCatalog = {
  providers: [
    {
      key: "rhoai",
      name: "Red Hat OpenShift AI",
      // Catalogue order, as the backend publishes it: TLS before the limit.
      credential_fields: [
        {
          key: "api_base",
          label: "Chat endpoint",
          required: true,
          field_type: "text",
        },
        {
          key: "embedding_api_base",
          label: "Embeddings endpoint",
          required: false,
          field_type: "text",
        },
        {
          key: "api_key",
          label: "ServiceAccount token",
          required: true,
          field_type: "password",
        },
        {
          key: "ssl_verify",
          label: "Verify TLS certificates",
          required: false,
          field_type: "tls_verify",
        },
        {
          key: "embedding_max_concurrency",
          label: "Max concurrent embedding requests",
          required: false,
          field_type: "text",
        },
      ],
      models: [],
      embedding_models: [],
    },
  ],
};

describe("ProviderSettingsDialog Red Hat OpenShift AI", () => {
  const rhoaiSaved = (credentialValues: Record<string, string> = {}) => ({
    provider: "rhoai",
    providerCatalog: rhoaiCatalog,
    credentialValues: {
      api_base: "https://chat.example.com/v1",
      ...credentialValues,
    },
    secretFields: ["api_key"],
    authMethod: "",
  });
  const embeddingsToggle = () =>
    screen.getByRole("button", { name: "Embeddings" });
  const advancedToggle = () =>
    screen.getByRole("button", { name: "Advanced settings" });
  const tlsSwitch = () =>
    screen.getByRole("switch", { name: "Verify TLS certificates" });
  const caPath = () =>
    screen.getByRole("textbox", { name: "Custom CA bundle path" });

  function expectInDocumentOrder(...elements: HTMLElement[]) {
    for (let i = 1; i < elements.length; i++) {
      expect(
        elements[i - 1].compareDocumentPosition(elements[i]) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
  }

  it("shows only the chat endpoint and token up front", async () => {
    renderDialog(rhoaiSaved());
    const user = userEvent.setup();

    const chat = await screen.findByLabelText(/^Chat endpoint/);
    expectInDocumentOrder(
      chat,
      screen.getByLabelText(/^ServiceAccount token/),
      embeddingsToggle(),
      advancedToggle(),
    );
    expect(embeddingsToggle()).toHaveAttribute("aria-expanded", "false");
    expect(advancedToggle()).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByLabelText(/^Embeddings endpoint/),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();

    await user.click(embeddingsToggle());
    await user.click(advancedToggle());

    expectInDocumentOrder(
      screen.getByLabelText(/^Embeddings endpoint/),
      screen.getByLabelText(/^Max concurrent embedding requests/),
      tlsSwitch(),
      caPath(),
    );
    expect(tlsSwitch()).toBeChecked();
    // The free-text field is replaced, never rendered alongside the switch.
    expect(
      screen.queryByRole("textbox", { name: /^Verify TLS certificates/ }),
    ).not.toBeInTheDocument();
  });

  it("opens Embeddings with a saved endpoint and treats editing it as a target change", async () => {
    const result = renderDialog(
      rhoaiSaved({ embedding_api_base: "https://embed.example.com/v1" }),
    );
    const user = userEvent.setup();

    const endpoint = await screen.findByLabelText(/^Embeddings endpoint/);
    expect(embeddingsToggle()).toHaveAttribute("aria-expanded", "true");
    expect(advancedToggle()).toHaveAttribute("aria-expanded", "false");
    expect(endpoint).toHaveValue("https://embed.example.com/v1");

    await user.clear(endpoint);
    await user.type(endpoint, "https://other-embed.example.com/v1");
    expect(screen.getByText(REENTRY_HINT)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText("ServiceAccount token is required"),
    ).toBeInTheDocument();
    expect(result.submitted).toBeUndefined();
  });

  it("saves false once verification is switched off and the token retyped", async () => {
    const result = renderDialog(rhoaiSaved());
    const user = userEvent.setup();

    await screen.findByText(SAVED_HINT);
    await user.click(advancedToggle());
    await user.click(tlsSwitch());
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Certificate verification is disabled.",
    );
    // A changed TLS setting is a new credential target.
    expect(screen.getByText(REENTRY_HINT)).toBeInTheDocument();
    await user.type(
      screen.getByLabelText(/^ServiceAccount token/),
      "sha256~new-token",
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(result.submitted).toEqual({
        provider_credentials: {
          rhoai: {
            api_base: "https://chat.example.com/v1",
            api_key: "sha256~new-token",
            ssl_verify: "false",
          },
        },
      });
    });
  });

  it("refuses to save a disabled TLS setting with the token kept", async () => {
    const result = renderDialog(rhoaiSaved());
    const user = userEvent.setup();

    await screen.findByText(SAVED_HINT);
    await user.click(advancedToggle());
    await user.click(tlsSwitch());
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText("ServiceAccount token is required"),
    ).toBeInTheDocument();
    expect(result.submitted).toBeUndefined();
  });

  it("removes a saved false once verification is switched back on", async () => {
    const result = renderDialog(rhoaiSaved({ ssl_verify: "false" }));
    const user = userEvent.setup();

    // Opened by itself: a disabled TLS setting is never hidden.
    const toggle = await screen.findByRole("switch", {
      name: "Verify TLS certificates",
    });
    expect(advancedToggle()).toHaveAttribute("aria-expanded", "true");
    expect(toggle).not.toBeChecked();

    await user.click(toggle);
    await user.type(
      screen.getByLabelText(/^ServiceAccount token/),
      "sha256~new-token",
    );
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      expect(result.submitted).toEqual({
        provider_credentials: {
          rhoai: {
            api_base: "https://chat.example.com/v1",
            api_key: "sha256~new-token",
          },
        },
        provider_credential_removals: { rhoai: ["ssl_verify"] },
      });
    });
  });

  it("opens Advanced with a saved CA path and treats editing it as a target change", async () => {
    renderDialog(rhoaiSaved({ ssl_verify: "/var/run/secrets/service-ca.crt" }));
    const user = userEvent.setup();

    await screen.findByRole("switch", { name: "Verify TLS certificates" });
    expect(caPath()).toHaveValue("/var/run/secrets/service-ca.crt");
    expect(screen.queryByText(REENTRY_HINT)).not.toBeInTheDocument();

    await user.type(caPath(), "x");

    expect(screen.getByText(REENTRY_HINT)).toBeInTheDocument();
  });

  it("opens Embeddings with a saved concurrency limit and saves a new one", async () => {
    const result = renderDialog(rhoaiSaved({ embedding_max_concurrency: "4" }));
    const user = userEvent.setup();

    const limit = await screen.findByLabelText(
      /^Max concurrent embedding requests/,
    );
    expect(limit).toHaveValue("4");
    await user.clear(limit);
    await user.type(limit, "16");
    await user.click(screen.getByRole("button", { name: "Save" }));

    // Not a credential target, so the saved token is kept.
    await waitFor(() => {
      expect(result.submitted).toEqual({
        provider_credentials: {
          rhoai: {
            api_base: "https://chat.example.com/v1",
            embedding_max_concurrency: "16",
          },
        },
      });
    });
  });

  it("keeps the saved token when verification is switched off and on again", async () => {
    renderDialog(rhoaiSaved());
    const user = userEvent.setup();

    await screen.findByText(SAVED_HINT);
    await user.click(advancedToggle());
    await user.click(tlsSwitch());
    await user.click(tlsSwitch());

    expect(screen.queryByText(REENTRY_HINT)).not.toBeInTheDocument();
    expect(screen.getByText(SAVED_HINT)).toBeInTheDocument();
  });

  it("restores the saved CA path when verification is switched back on after Advanced was collapsed", async () => {
    renderDialog(rhoaiSaved({ ssl_verify: "/var/run/secrets/service-ca.crt" }));
    const user = userEvent.setup();

    await screen.findByRole("switch", { name: "Verify TLS certificates" });
    await user.click(tlsSwitch());
    await user.click(advancedToggle());
    await user.click(advancedToggle());
    await user.click(tlsSwitch());

    expect(caPath()).toHaveValue("/var/run/secrets/service-ca.crt");
    expect(screen.queryByText(REENTRY_HINT)).not.toBeInTheDocument();
  });
});
