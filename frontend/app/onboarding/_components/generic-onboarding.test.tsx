import { HttpResponse, http, type RequestHandler } from "msw";
import type { Dispatch, SetStateAction } from "react";
import { describe, expect, it } from "vitest";
import type { OnboardingVariables } from "@/app/api/mutations/useOnboardingMutation";
import type { SavedProvidersSnapshot } from "@/components/models/catalog-models";
import {
  renderWithProviders,
  screen,
  userEvent,
  waitFor,
} from "@/test-utils/render";
import { GenericOnboarding } from "./generic-onboarding";

const catalog = {
  providers: [
    {
      key: "azure",
      name: "Azure OpenAI",
      credential_fields: [],
      models: [{ model: "gpt-5.5", capabilities: ["function_calling"] }],
      embedding_models: [{ model: "text-embedding-3-small" }],
    },
    {
      key: "openai_like",
      name: "Other provider",
      credential_fields: [
        {
          key: "api_base",
          label: "API base",
          required: false,
          field_type: "text",
        },
      ],
      models: [{ model: "gpt-4.1", capabilities: ["function_calling"] }],
      embedding_models: [
        { model: "text-embedding-3-small" },
        { model: "text-embedding-3-large" },
      ],
    },
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
      models: [
        {
          model: "ibm/granite-3-8b-instruct",
          capabilities: ["function_calling"],
        },
      ],
      embedding_models: [],
    },
    {
      key: "rhoai",
      name: "Red Hat OpenShift AI",
      discovers_models: true,
      credential_fields: [
        {
          key: "api_base",
          label: "Chat endpoint",
          required: true,
          field_type: "text",
        },
        {
          key: "embedding_api_base",
          label: "Embedding endpoint",
          required: false,
          field_type: "text",
        },
        {
          key: "api_key",
          label: "Token",
          required: true,
          field_type: "password",
        },
        // Catalogue order, as the backend publishes it: TLS before the limit.
        {
          key: "ssl_verify",
          label: "TLS certificate verification",
          required: false,
          field_type: "text",
        },
        {
          key: "embedding_max_concurrency",
          label: "Max concurrent embedding requests",
          required: false,
          field_type: "text",
        },
      ],
      models: [{ model: "granite-3.3-2b-instruct", mode: "chat" }],
      embedding_models: [
        { model: "granite-embedding-english-r2", mode: "embedding" },
      ],
    },
  ],
};

function renderOnboarding(
  provider: string,
  isEmbedding = false,
  savedProviders?: SavedProvidersSnapshot,
  extraHandlers: RequestHandler[] = [],
  catalogResponse: { providers: object[] } = catalog,
) {
  let settings: OnboardingVariables = {};
  // Every model the parent was handed, in order.
  const modelHistory: Array<string | undefined> = [];
  const setSettings: Dispatch<SetStateAction<OnboardingVariables>> = (next) => {
    settings = typeof next === "function" ? next(settings) : next;
    modelHistory.push(
      isEmbedding ? settings.embedding_model : settings.llm_model,
    );
  };
  let blocker: string | null = null;
  const user = userEvent.setup();
  const view = renderWithProviders(
    <GenericOnboarding
      provider={provider}
      isEmbedding={isEmbedding}
      setSettings={setSettings}
      providers={savedProviders}
      onCompletionBlockerChange={(next) => {
        blocker = next;
      }}
    />,
    {
      providers: ["tooltip"],
      handlers: [
        http.get("/api/models/catalog", () =>
          HttpResponse.json(catalogResponse),
        ),
        http.post("/api/models/watsonx_onprem/spaces", () =>
          HttpResponse.json({
            spaces: [
              { id: "space-prod", name: "Production" },
              { id: "space-dev", name: "Development" },
            ],
          }),
        ),
        ...extraHandlers,
      ],
    },
  );
  return {
    user,
    getSettings: () => settings,
    getBlocker: () => blocker,
    unmount: view.unmount,
    modelHistory,
  };
}

describe("GenericOnboarding model selection", () => {
  it.each([
    {
      kind: "language",
      isEmbedding: false,
      selectorName: "Language model",
      modelKey: "llm_model",
      catalogModel: "gpt-5.5",
    },
    {
      kind: "embedding",
      isEmbedding: true,
      selectorName: "Embedding model",
      modelKey: "embedding_model",
      catalogModel: "text-embedding-3-small",
    },
  ] as const)("requires an explicit Azure $kind model choice", async (testCase) => {
    const { user, getSettings } = renderOnboarding(
      "azure",
      testCase.isEmbedding,
    );
    const selector = await screen.findByRole("combobox", {
      name: testCase.selectorName,
    });
    await user.click(selector);
    const catalogOption = await screen.findByRole("option", {
      name: testCase.catalogModel,
    });

    expect(selector).toHaveTextContent("Select model...");
    expect(getSettings()[testCase.modelKey]).toBeFalsy();

    await user.click(catalogOption);
    expect(getSettings()[testCase.modelKey]).toBe(testCase.catalogModel);
  });

  it("keeps automatic defaults for other generic providers", async () => {
    const { user, getSettings } = renderOnboarding("openai_like");
    await user.click(
      await screen.findByRole("combobox", { name: "Language model" }),
    );
    await screen.findByRole("option", { name: "gpt-4.1" });
    expect(getSettings().llm_model).toBe("gpt-4.1");
  });

  it("seeds saved credentials and synchronizes edits to parent settings", async () => {
    const { user, getSettings } = renderOnboarding("openai_like", false, {
      custom: {
        openai_like: {
          credential_values: { api_base: "https://saved.example" },
        },
      },
    });
    await user.click(
      await screen.findByRole("combobox", { name: "Language model" }),
    );
    await screen.findByRole("option", { name: "gpt-4.1" });

    const apiBase = screen.getByLabelText("API base");
    expect(apiBase).toHaveValue("https://saved.example");
    expect(getSettings().provider_credentials?.openai_like?.api_base).toBe(
      "https://saved.example",
    );

    await user.clear(apiBase);
    await user.type(apiBase, "https://new.example");
    expect(getSettings().provider_credentials?.openai_like?.api_base).toBe(
      "https://new.example",
    );
  });

  it("keeps watsonx on-prem TLS configuration provider-scoped", async () => {
    const { user, getSettings } = renderOnboarding("watsonx_onprem");

    await user.click(
      await screen.findByRole("button", { name: "Advanced settings" }),
    );
    const verifyTls = screen.getByRole("switch", {
      name: "Verify TLS certificates",
    });

    expect(verifyTls).toBeChecked();
    const caPath = screen.getByRole("textbox", {
      name: "Custom CA bundle path",
    });
    await user.type(caPath, "/etc/ssl/certs/openrag-ca.pem");
    expect(getSettings().provider_credentials?.watsonx_onprem?.ssl_verify).toBe(
      "/etc/ssl/certs/openrag-ca.pem",
    );
  });

  it("marks a cleared saved field for removal during onboarding", async () => {
    const { user, getSettings } = renderOnboarding("watsonx_onprem", false, {
      custom: {
        watsonx_onprem: {
          credential_values: {
            api_base: "https://cpd.example.com",
            space_id: "deployment-space",
            ssl_verify: "true",
          },
        },
      },
    });

    await user.click(
      await screen.findByRole("button", { name: "Advanced settings" }),
    );
    expect(
      screen.getByRole("combobox", { name: "Deployment space ID" }),
    ).toHaveTextContent("deployment-space");

    await user.click(
      screen.getByRole("button", { name: "Clear deployment space" }),
    );
    expect(getSettings().provider_credential_removals?.watsonx_onprem).toEqual([
      "space_id",
    ]);
  });

  it("loads and selects an available deployment space during onboarding", async () => {
    const { user, getSettings } = renderOnboarding("watsonx_onprem", false, {
      custom: {
        watsonx_onprem: {
          auth_method: "username_api_key",
          credential_values: {
            api_base: "https://cpd.example.com",
            username: "cpd-user",
            ssl_verify: "true",
          },
          secret_fields: ["api_key"],
        },
      },
    });

    await user.click(
      await screen.findByRole("button", { name: "Advanced settings" }),
    );
    const spaceSelect = screen.getByRole("combobox", {
      name: "Deployment space ID",
    });
    await user.click(spaceSelect);
    await user.click(
      await screen.findByRole("option", { name: /Production.*space-prod/ }),
    );

    expect(getSettings().provider_credentials?.watsonx_onprem?.space_id).toBe(
      "space-prod",
    );

    await user.click(spaceSelect);
    await user.type(
      screen.getByPlaceholderText("Search or enter a deployment space ID…"),
      "manually-entered-space",
    );
    await user.click(
      await screen.findByRole("option", {
        name: /Use manually-entered-space as deployment space ID/,
      }),
    );
    expect(getSettings().provider_credentials?.watsonx_onprem?.space_id).toBe(
      "manually-entered-space",
    );
  });

  it("updates the selected embedding model for another generic provider", async () => {
    const { user, getSettings } = renderOnboarding("openai_like", true);
    await user.click(
      await screen.findByRole("combobox", { name: "Embedding model" }),
    );
    await user.click(
      await screen.findByRole("option", { name: "text-embedding-3-large" }),
    );
    expect(getSettings().embedding_model).toBe("text-embedding-3-large");
  });
});

describe("GenericOnboarding cluster model discovery", () => {
  // Debounce (500 ms) plus the request.
  const DISCOVERY_TIMEOUT = { timeout: 3000 };

  type DiscoverRequest = {
    credentials: Record<string, string>;
    kind?: string;
  };

  function discoverHandler(
    response: () => Response,
    requests: DiscoverRequest[] = [],
  ) {
    return http.post("/api/models/rhoai/discover", async ({ request }) => {
      requests.push((await request.json()) as DiscoverRequest);
      return response();
    });
  }

  const served = () =>
    HttpResponse.json({
      models: [{ model: "gpt-oss-120b", mode: "chat" }],
      embedding_models: [{ model: "nomic-embed-text", mode: "embedding" }],
    });

  async function typeCredentials(user: ReturnType<typeof userEvent.setup>) {
    await user.type(
      await screen.findByLabelText(/Chat endpoint/),
      "https://chat.example.com/v1",
    );
    await user.type(screen.getByLabelText(/Token/), "sha256~token");
  }

  it("offers the models the cluster serves instead of the configured fallback", async () => {
    const requests: DiscoverRequest[] = [];
    const { user, getSettings } = renderOnboarding("rhoai", false, undefined, [
      discoverHandler(served, requests),
    ]);
    await waitFor(() =>
      expect(getSettings().llm_model).toBe("granite-3.3-2b-instruct"),
    );

    await typeCredentials(user);

    expect(
      await screen.findByText(
        "Showing 1 language model served by the cluster.",
        {},
        DISCOVERY_TIMEOUT,
      ),
    ).toBeInTheDocument();
    // The automatic default follows the list; the cluster does not serve granite.
    expect(getSettings().llm_model).toBe("gpt-oss-120b");
    expect(requests.at(-1)?.credentials).toEqual({
      api_base: "https://chat.example.com/v1",
      api_key: "sha256~token",
    });
    // Only the chat endpoint is asked, so a dead embedding endpoint can't
    // stall this step.
    expect(requests.at(-1)?.kind).toBe("chat");

    await user.click(screen.getByRole("combobox", { name: "Language model" }));
    expect(
      await screen.findByRole("option", { name: "gpt-oss-120b" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "granite-3.3-2b-instruct" }),
    ).not.toBeInTheDocument();
  });

  it("uses the embedding endpoint's listing for the embedding picker", async () => {
    const requests: DiscoverRequest[] = [];
    const { user, getSettings } = renderOnboarding("rhoai", true, undefined, [
      discoverHandler(served, requests),
    ]);

    await typeCredentials(user);

    await screen.findByText(
      "Showing 1 embedding model served by the cluster.",
      {},
      DISCOVERY_TIMEOUT,
    );
    expect(getSettings().embedding_model).toBe("nomic-embed-text");
    expect(requests.at(-1)?.kind).toBe("embedding");
  });

  it("keeps a model the user chose even when the cluster does not list it", async () => {
    const { user, getSettings } = renderOnboarding("rhoai", false, undefined, [
      discoverHandler(served),
    ]);
    await user.click(
      await screen.findByRole("combobox", { name: "Language model" }),
    );
    await user.click(
      await screen.findByRole("option", { name: "granite-3.3-2b-instruct" }),
    );

    await typeCredentials(user);

    await screen.findByText(
      "Showing 1 language model served by the cluster.",
      {},
      DISCOVERY_TIMEOUT,
    );
    expect(getSettings().llm_model).toBe("granite-3.3-2b-instruct");
  });

  it("falls back to the configured models when the cluster cannot be listed", async () => {
    const { user, getSettings } = renderOnboarding("rhoai", false, undefined, [
      discoverHandler(() =>
        HttpResponse.json({ models: null, embedding_models: null }),
      ),
    ]);

    await typeCredentials(user);

    expect(
      await screen.findByText(
        /Couldn't list language models from the cluster/,
        {},
        DISCOVERY_TIMEOUT,
      ),
    ).toBeInTheDocument();
    expect(getSettings().llm_model).toBe("granite-3.3-2b-instruct");
  });

  it("reports a failed discovery request the same way", async () => {
    const { user } = renderOnboarding("rhoai", false, undefined, [
      discoverHandler(() =>
        HttpResponse.json(
          { error: "Unable to list models from the provider." },
          { status: 500 },
        ),
      ),
    ]);

    await typeCredentials(user);

    expect(
      await screen.findByText(
        /Couldn't list language models from the cluster/,
        {},
        DISCOVERY_TIMEOUT,
      ),
    ).toBeInTheDocument();
  });

  it("does not ask the cluster until the required credentials are filled", async () => {
    const requests: Array<{ credentials: Record<string, string> }> = [];
    const { user } = renderOnboarding("rhoai", false, undefined, [
      discoverHandler(served, requests),
    ]);

    await user.type(
      await screen.findByLabelText(/Chat endpoint/),
      "https://chat.example.com/v1",
    );
    await new Promise((resolve) => setTimeout(resolve, 800));

    expect(requests).toHaveLength(0);
  });

  it("reuses a saved token without retyping it", async () => {
    const requests: Array<{ credentials: Record<string, string> }> = [];
    renderOnboarding(
      "rhoai",
      false,
      {
        custom: {
          rhoai: {
            credential_values: { api_base: "https://chat.example.com/v1" },
            secret_fields: ["api_key"],
          },
        },
      },
      [discoverHandler(served, requests)],
    );

    await screen.findByText(
      "Showing 1 language model served by the cluster.",
      {},
      DISCOVERY_TIMEOUT,
    );
    // The backend fills the saved token in; it never reaches the browser.
    expect(requests.at(-1)?.credentials).toEqual({
      api_base: "https://chat.example.com/v1",
    });
  });

  it("asks for the token again once the endpoint changes", async () => {
    const requests: Array<{ credentials: Record<string, string> }> = [];
    const { user } = renderOnboarding(
      "rhoai",
      false,
      {
        custom: {
          rhoai: {
            credential_values: { api_base: "https://chat.example.com/v1" },
            secret_fields: ["api_key"],
          },
        },
      },
      [discoverHandler(served, requests)],
    );
    const endpoint = await screen.findByLabelText(/Chat endpoint/);
    expect(
      screen.getByText(
        "A value is already saved. Leave this blank to keep it.",
      ),
    ).toBeInTheDocument();

    await user.clear(endpoint);
    await user.type(endpoint, "https://other.example.com/v1");

    // The backend drops the saved token for a new host, so it no longer counts.
    expect(
      screen.queryByText(
        "A value is already saved. Leave this blank to keep it.",
      ),
    ).not.toBeInTheDocument();
    const asked = requests.length;
    await new Promise((resolve) => setTimeout(resolve, 800));
    expect(
      requests
        .slice(asked)
        .some((r) => r.credentials.api_base === "https://other.example.com/v1"),
    ).toBe(false);

    await user.type(screen.getByLabelText(/Token/), "sha256~new-token");
    await waitFor(
      () =>
        expect(requests.at(-1)?.credentials).toEqual({
          api_base: "https://other.example.com/v1",
          api_key: "sha256~new-token",
        }),
      DISCOVERY_TIMEOUT,
    );
  });

  describe("Submit gate for a changed target", () => {
    const savedToken: SavedProvidersSnapshot = {
      custom: {
        rhoai: {
          credential_values: { api_base: "https://chat.example.com/v1" },
          secret_fields: ["api_key"],
        },
      },
    };
    const blockerText =
      "Enter Token again: the endpoint or TLS setting changed.";
    const hintText =
      "The endpoint or TLS setting changed, so the saved value is not sent to it. Enter it again.";

    it("does not block while the saved endpoint is kept", async () => {
      const { getBlocker } = renderOnboarding("rhoai", false, savedToken);
      await screen.findByLabelText(/Chat endpoint/);

      expect(getBlocker()).toBeNull();
      expect(screen.queryByText(hintText)).not.toBeInTheDocument();
    });

    it("blocks until the saved token is typed again", async () => {
      const { user, getBlocker } = renderOnboarding("rhoai", false, savedToken);
      const endpoint = await screen.findByLabelText(/Chat endpoint/);

      await user.clear(endpoint);
      await user.type(endpoint, "https://other.example.com/v1");

      expect(getBlocker()).toBe(blockerText);
      expect(screen.getByText(hintText)).toBeInTheDocument();

      await user.type(screen.getByLabelText(/Token/), "sha256~new-token");

      expect(getBlocker()).toBeNull();
      expect(screen.queryByText(hintText)).not.toBeInTheDocument();
    });

    it("unblocks when the saved endpoint is restored", async () => {
      const { user, getBlocker } = renderOnboarding("rhoai", false, savedToken);
      const endpoint = await screen.findByLabelText(/Chat endpoint/);

      await user.type(endpoint, "x");
      expect(getBlocker()).toBe(blockerText);

      await user.type(endpoint, "{Backspace}");
      expect(getBlocker()).toBeNull();
    });

    it("stops blocking once the tab is left", async () => {
      const { user, getBlocker, unmount } = renderOnboarding(
        "rhoai",
        false,
        savedToken,
      );
      await user.type(await screen.findByLabelText(/Chat endpoint/), "x");
      expect(getBlocker()).toBe(blockerText);

      unmount();

      expect(getBlocker()).toBeNull();
    });

    it("ignores a saved secret the chosen auth method does not use", async () => {
      const { user, getBlocker } = renderOnboarding("watsonx_onprem", false, {
        custom: {
          watsonx_onprem: {
            auth_method: "username_api_key",
            credential_values: {
              api_base: "https://cpd.example.com",
              username: "cpd-user",
            },
            secret_fields: ["api_key", "zen_api_key"],
          },
        },
      });
      const endpoint = await screen.findByLabelText(/Cluster URL/);

      await user.clear(endpoint);
      await user.type(endpoint, "https://other-cpd.example.com");

      // Only the username + API key method is active, so only its key counts.
      expect(getBlocker()).toBe(
        "Enter API key again: the endpoint or TLS setting changed.",
      );
    });
  });

  it("treats a cleared saved endpoint as a new target", async () => {
    const requests: Array<{ credentials: Record<string, string> }> = [];
    const { user, getSettings } = renderOnboarding(
      "rhoai",
      true,
      {
        custom: {
          rhoai: {
            credential_values: {
              api_base: "https://chat.example.com/v1",
              embedding_api_base: "https://embed.example.com/v1",
            },
            secret_fields: ["api_key"],
          },
        },
      },
      [discoverHandler(served, requests)],
    );
    await screen.findByText(
      "Showing 1 embedding model served by the cluster.",
      {},
      DISCOVERY_TIMEOUT,
    );

    await user.clear(screen.getByLabelText(/Embedding endpoint/));

    // Submit removes the endpoint, so embeddings go to the chat endpoint: the
    // saved token no longer counts, and nothing is asked until it is retyped.
    expect(getSettings().provider_credential_removals?.rhoai).toEqual([
      "embedding_api_base",
    ]);
    expect(
      screen.queryByText(
        "A value is already saved. Leave this blank to keep it.",
      ),
    ).not.toBeInTheDocument();
    const asked = requests.length;
    await new Promise((resolve) => setTimeout(resolve, 800));
    expect(requests.length).toBe(asked);

    await user.type(screen.getByLabelText(/Token/), "sha256~new-token");
    // Sent blank, so the backend does not fill the saved endpoint back in.
    await waitFor(
      () =>
        expect(requests.at(-1)?.credentials).toEqual({
          api_base: "https://chat.example.com/v1",
          embedding_api_base: "",
          api_key: "sha256~new-token",
        }),
      DISCOVERY_TIMEOUT,
    );
  });

  it("keeps the discovered model while the cluster is asked again", async () => {
    let calls = 0;
    let release: () => void = () => {};
    const { user, getSettings, modelHistory } = renderOnboarding(
      "rhoai",
      false,
      undefined,
      [
        http.post("/api/models/rhoai/discover", async () => {
          calls += 1;
          if (calls === 1) return served();
          await new Promise<void>((resolve) => {
            release = resolve;
          });
          return HttpResponse.json({
            models: [{ model: "gpt-oss-20b", mode: "chat" }],
            embedding_models: null,
          });
        }),
      ],
    );

    await typeCredentials(user);
    await screen.findByText(
      "Showing 1 language model served by the cluster.",
      {},
      DISCOVERY_TIMEOUT,
    );
    expect(getSettings().llm_model).toBe("gpt-oss-120b");
    const discoveredAt = modelHistory.lastIndexOf("gpt-oss-120b");

    await user.type(screen.getByLabelText(/Token/), "2");
    await screen.findByText(
      "Checking which models the cluster serves…",
      {},
      DISCOVERY_TIMEOUT,
    );
    // The configured fallback must not be handed over while the cluster is
    // being asked again.
    expect(getSettings().llm_model).toBe("gpt-oss-120b");

    // The status reflects the query, not the handler; release only once the
    // handler has installed its resolver.
    await waitFor(() => expect(calls).toBe(2), DISCOVERY_TIMEOUT);
    release();
    await screen.findByText(
      "Showing 1 language model served by the cluster.",
      {},
      DISCOVERY_TIMEOUT,
    );
    await waitFor(() => expect(getSettings().llm_model).toBe("gpt-oss-20b"));
    expect(modelHistory.slice(discoveredAt)).not.toContain(
      "granite-3.3-2b-instruct",
    );
  });

  it("selects the configured fallback while saved credentials are first checked", async () => {
    let asked = false;
    let release: () => void = () => {};
    const { getSettings } = renderOnboarding(
      "rhoai",
      false,
      {
        custom: {
          rhoai: {
            credential_values: { api_base: "https://chat.example.com/v1" },
            secret_fields: ["api_key"],
          },
        },
      },
      [
        http.post("/api/models/rhoai/discover", async () => {
          await new Promise<void>((resolve) => {
            release = resolve;
            asked = true;
          });
          return served();
        }),
      ],
    );

    await screen.findByText(
      "Checking which models the cluster serves…",
      {},
      DISCOVERY_TIMEOUT,
    );
    // Saved credentials make the first render already in flight; a slow
    // cluster must not leave Submit without a model meanwhile.
    await waitFor(() =>
      expect(getSettings().llm_model).toBe("granite-3.3-2b-instruct"),
    );

    // Release only once the handler has installed its resolver.
    await waitFor(() => expect(asked).toBe(true), DISCOVERY_TIMEOUT);
    release();
    await screen.findByText(
      "Showing 1 language model served by the cluster.",
      {},
      DISCOVERY_TIMEOUT,
    );
    await waitFor(() => expect(getSettings().llm_model).toBe("gpt-oss-120b"));
  });

  describe("with no configured fallback", () => {
    const noFallbackCatalog = {
      ...catalog,
      providers: catalog.providers.map((entry) =>
        entry.key === "rhoai"
          ? { ...entry, models: [], embedding_models: [] }
          : entry,
      ),
    };

    it("asks for credentials instead of sending the operator elsewhere", async () => {
      renderOnboarding("rhoai", false, undefined, [], noFallbackCatalog);

      expect(
        await screen.findByText(
          "Enter the credentials above to list the language models the cluster serves.",
        ),
      ).toBeInTheDocument();
      expect(
        screen.queryByText(/Pick a different provider/),
      ).not.toBeInTheDocument();
    });

    it("asks for a model ID when the cluster cannot be listed", async () => {
      const { user } = renderOnboarding(
        "rhoai",
        false,
        undefined,
        [
          discoverHandler(() =>
            HttpResponse.json({ models: null, embedding_models: null }),
          ),
        ],
        noFallbackCatalog,
      );

      await typeCredentials(user);

      expect(
        await screen.findByText(
          "Couldn't list language models from the cluster. Type a model ID to continue.",
          {},
          DISCOVERY_TIMEOUT,
        ),
      ).toBeInTheDocument();
      expect(screen.queryByText(/configured defaults/)).not.toBeInTheDocument();
      expect(
        screen.queryByText(/Pick a different provider/),
      ).not.toBeInTheDocument();
    });

    it("says so when the cluster lists nothing for this picker", async () => {
      const { user } = renderOnboarding(
        "rhoai",
        true,
        undefined,
        [
          discoverHandler(() =>
            HttpResponse.json({
              models: [{ model: "gpt-oss-120b", mode: "chat" }],
              embedding_models: [],
            }),
          ),
        ],
        noFallbackCatalog,
      );

      await typeCredentials(user);

      expect(
        await screen.findByText(
          "The cluster lists no embedding models. Type a model ID to continue.",
          {},
          DISCOVERY_TIMEOUT,
        ),
      ).toBeInTheDocument();
    });
  });

  it("clears the automatic fallback when the cluster lists nothing", async () => {
    const { user, getSettings } = renderOnboarding("rhoai", true, undefined, [
      discoverHandler(() =>
        HttpResponse.json({
          models: [{ model: "gpt-oss-120b", mode: "chat" }],
          embedding_models: [],
        }),
      ),
    ]);
    await waitFor(() =>
      expect(getSettings().embedding_model).toBe(
        "granite-embedding-english-r2",
      ),
    );

    await typeCredentials(user);

    await screen.findByText(
      "The cluster lists no embedding models. Type a model ID to continue.",
      {},
      DISCOVERY_TIMEOUT,
    );
    // The cluster does not serve the fallback, so "Complete" must not send it.
    expect(getSettings().embedding_model).toBe("");
  });

  it("still sends the operator elsewhere for a provider that cannot discover", async () => {
    renderOnboarding("watsonx_onprem", true);

    expect(
      await screen.findByText(/publishes no embedding models in the catalogue/),
    ).toBeInTheDocument();
  });

  describe("for watsonx.ai on-prem's username + API key method", () => {
    // As the backend declares it: `username` is optional, because the Zen API
    // key method does not use it.
    const discoveringOnPrem = {
      ...catalog,
      providers: catalog.providers.map((entry) =>
        entry.key === "watsonx_onprem"
          ? {
              ...entry,
              discovers_models: true,
              credential_fields: entry.credential_fields.map((field) =>
                field.key === "username"
                  ? { ...field, required: false }
                  : field,
              ),
            }
          : entry,
      ),
    };

    function onPremDiscoverHandler(
      requests: Array<{ credentials: Record<string, string> }>,
    ) {
      return http.post(
        "/api/models/watsonx_onprem/discover",
        async ({ request }) => {
          requests.push(
            (await request.json()) as { credentials: Record<string, string> },
          );
          return HttpResponse.json({
            models: [{ model: "ibm/granite-4-h-small", mode: "chat" }],
            embedding_models: [],
          });
        },
      );
    }

    it("does not ask the cluster without a username", async () => {
      const requests: Array<{ credentials: Record<string, string> }> = [];
      const { user } = renderOnboarding(
        "watsonx_onprem",
        false,
        undefined,
        [onPremDiscoverHandler(requests)],
        discoveringOnPrem,
      );

      await user.type(
        await screen.findByLabelText(/Cluster URL/),
        "https://cpd.example.com",
      );
      await user.type(screen.getByLabelText(/^API key/), "cpd-api-key");
      await new Promise((resolve) => setTimeout(resolve, 800));

      expect(requests).toHaveLength(0);
      expect(
        screen.queryByText(/Couldn't list language models from the cluster/),
      ).not.toBeInTheDocument();
    });

    it("asks the cluster once the username is filled", async () => {
      const requests: Array<{ credentials: Record<string, string> }> = [];
      const { user } = renderOnboarding(
        "watsonx_onprem",
        false,
        undefined,
        [onPremDiscoverHandler(requests)],
        discoveringOnPrem,
      );

      await user.type(
        await screen.findByLabelText(/Cluster URL/),
        "https://cpd.example.com",
      );
      await user.type(screen.getByLabelText(/^API key/), "cpd-api-key");
      await user.type(screen.getByLabelText("Username"), "cpd-user");

      expect(
        await screen.findByText(
          "Showing 1 language model served by the cluster.",
          {},
          DISCOVERY_TIMEOUT,
        ),
      ).toBeInTheDocument();
      expect(requests.at(-1)?.credentials).toEqual({
        api_base: "https://cpd.example.com",
        username: "cpd-user",
        api_key: "cpd-api-key",
      });
    });

    describe("when the auth method is switched", () => {
      // The Zen API key method's own field, which the shared catalogue above
      // leaves out.
      const withZenKeyField = {
        ...discoveringOnPrem,
        providers: discoveringOnPrem.providers.map((entry) =>
          entry.key === "watsonx_onprem"
            ? {
                ...entry,
                credential_fields: [
                  ...entry.credential_fields,
                  {
                    key: "zen_api_key",
                    label: "Zen API key",
                    required: false,
                    field_type: "password",
                  },
                ],
              }
            : entry,
        ),
      };
      const savedZenKey: SavedProvidersSnapshot = {
        custom: {
          watsonx_onprem: {
            auth_method: "zen_api_key",
            credential_values: { api_base: "https://cpd.example.com" },
            secret_fields: ["zen_api_key"],
          },
        },
      };
      const servedStatus = "Showing 1 language model served by the cluster.";
      // Longer than the typing debounce, so a late second request would land.
      const settle = () => new Promise((resolve) => setTimeout(resolve, 800));
      type OnPremRequest = {
        credentials: Record<string, string>;
        auth_method?: string;
        kind?: string;
      };

      it("asks once, with only the new method's fields", async () => {
        const requests: OnPremRequest[] = [];
        const { user } = renderOnboarding(
          "watsonx_onprem",
          false,
          {
            custom: {
              watsonx_onprem: {
                auth_method: "username_api_key",
                credential_values: {
                  api_base: "https://cpd.example.com",
                  username: "cpd-user",
                },
                secret_fields: ["api_key", "zen_api_key"],
              },
            },
          },
          [onPremDiscoverHandler(requests)],
          withZenKeyField,
        );
        await screen.findByText(servedStatus, {}, DISCOVERY_TIMEOUT);
        expect(requests.at(-1)).toMatchObject({
          credentials: {
            api_base: "https://cpd.example.com",
            username: "cpd-user",
          },
          auth_method: "username_api_key",
        });
        const asked = requests.length;

        await user.click(screen.getByRole("button", { name: /Zen API key/ }));
        await settle();

        // The saved Zen key makes the method ready at once; the username
        // typed for the other method must not ride along under its name.
        expect(requests.slice(asked)).toEqual([
          {
            credentials: { api_base: "https://cpd.example.com" },
            auth_method: "zen_api_key",
            kind: "chat",
          },
        ]);
        expect(screen.getByText(servedStatus)).toBeInTheDocument();
      });

      it("does not re-ask with the other method's fields when switching back", async () => {
        const requests: OnPremRequest[] = [];
        const { user } = renderOnboarding(
          "watsonx_onprem",
          false,
          savedZenKey,
          [onPremDiscoverHandler(requests)],
          withZenKeyField,
        );
        await screen.findByText(servedStatus, {}, DISCOVERY_TIMEOUT);

        await user.click(
          screen.getByRole("button", { name: /Username \+ API key/ }),
        );
        await user.type(screen.getByLabelText("Username"), "cpd-user");
        await user.type(screen.getByLabelText(/^API key/), "cpd-api-key");
        await waitFor(
          () => expect(requests.at(-1)?.auth_method).toBe("username_api_key"),
          DISCOVERY_TIMEOUT,
        );
        await screen.findByText(servedStatus, {}, DISCOVERY_TIMEOUT);
        await settle();
        const asked = requests.length;

        await user.click(screen.getByRole("button", { name: /Zen API key/ }));
        await settle();

        // Asked with the Zen key on mount, so the answer is cached: nothing
        // goes out, rather than the typed username + API key under its name.
        expect(requests.slice(asked)).toEqual([]);
        expect(screen.getByText(servedStatus)).toBeInTheDocument();
      });

      it("keeps the discovered model when switching to a method already typed", async () => {
        const requests: OnPremRequest[] = [];
        const { user, getSettings, modelHistory } = renderOnboarding(
          "watsonx_onprem",
          false,
          savedZenKey,
          [onPremDiscoverHandler(requests)],
          withZenKeyField,
        );
        await screen.findByText(servedStatus, {}, DISCOVERY_TIMEOUT);

        await user.click(
          screen.getByRole("button", { name: /Username \+ API key/ }),
        );
        await user.type(screen.getByLabelText("Username"), "cpd-user");
        await user.type(screen.getByLabelText(/^API key/), "cpd-api-key");
        await waitFor(
          () => expect(requests.at(-1)?.auth_method).toBe("username_api_key"),
          DISCOVERY_TIMEOUT,
        );
        await user.click(screen.getByRole("button", { name: /Zen API key/ }));
        await settle();
        expect(getSettings().llm_model).toBe("ibm/granite-4-h-small");
        const switchedAt = modelHistory.length;

        await user.click(
          screen.getByRole("button", { name: /Username \+ API key/ }),
        );
        await settle();

        // The typed username already counts for the method switched to, so
        // the picker must not fall back to the configured model meanwhile.
        expect(modelHistory.slice(switchedAt)).not.toContain(
          "ibm/granite-3-8b-instruct",
        );
        expect(getSettings().llm_model).toBe("ibm/granite-4-h-small");
      });
    });
  });

  it("never asks a provider that cannot list its models", async () => {
    const requests: Array<{ credentials: Record<string, string> }> = [];
    const { user } = renderOnboarding("openai_like", false, undefined, [
      http.post("/api/models/openai_like/discover", async ({ request }) => {
        requests.push(
          (await request.json()) as { credentials: Record<string, string> },
        );
        return HttpResponse.json({ models: [], embedding_models: [] });
      }),
    ]);

    await user.type(
      await screen.findByLabelText("API base"),
      "https://other.example",
    );
    await new Promise((resolve) => setTimeout(resolve, 800));

    expect(requests).toHaveLength(0);
  });
});

describe("GenericOnboarding RHOAI sections", () => {
  const embeddingsToggle = () =>
    screen.getByRole("button", { name: "Embeddings" });
  const advancedToggle = () =>
    screen.getByRole("button", { name: "Advanced settings" });
  const tlsSwitch = () =>
    screen.getByRole("switch", { name: "Verify TLS certificates" });
  const embeddingEndpoint = () =>
    screen.getByRole("textbox", { name: /Embedding endpoint/ });
  const concurrency = () =>
    screen.getByRole("textbox", { name: /Max concurrent embedding requests/ });
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

  const savedRhoai = (
    credentialValues: Record<string, string>,
    secretFields: string[] = [],
  ): SavedProvidersSnapshot => ({
    custom: {
      rhoai: {
        credential_values: {
          api_base: "https://chat.example.com/v1",
          ...credentialValues,
        },
        secret_fields: secretFields,
      },
    },
  });

  it("shows only the chat endpoint and token up front in the language step", async () => {
    renderOnboarding("rhoai");

    const chat = await screen.findByLabelText(/Chat endpoint/);
    expectInDocumentOrder(
      chat,
      screen.getByLabelText(/Token/),
      embeddingsToggle(),
      advancedToggle(),
    );
    expect(embeddingsToggle()).toHaveAttribute("aria-expanded", "false");
    expect(advancedToggle()).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.queryByLabelText(/Embedding endpoint/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText(/Max concurrent embedding requests/),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("switch")).not.toBeInTheDocument();
    // The free-text field is replaced, never rendered alongside the switch.
    expect(
      screen.queryByLabelText(/TLS certificate verification/),
    ).not.toBeInTheDocument();
  });

  it("opens Embeddings in the embedding step, where its endpoint matters", async () => {
    renderOnboarding("rhoai", true);

    await screen.findByLabelText(/Chat endpoint/);
    expect(embeddingsToggle()).toHaveAttribute("aria-expanded", "true");
    expect(embeddingEndpoint()).toBeInTheDocument();
    expect(advancedToggle()).toHaveAttribute("aria-expanded", "false");
  });

  it("orders the fields inside each section", async () => {
    const { user } = renderOnboarding("rhoai");
    await user.click(await screen.findByRole("button", { name: "Embeddings" }));
    await user.click(advancedToggle());

    expectInDocumentOrder(
      embeddingEndpoint(),
      concurrency(),
      tlsSwitch(),
      caPath(),
    );
    // Verification is on unless the operator turns it off.
    expect(tlsSwitch()).toBeChecked();
  });

  it("submits false when verification is switched off", async () => {
    const { user, getSettings } = renderOnboarding("rhoai");
    await user.click(
      await screen.findByRole("button", { name: "Advanced settings" }),
    );

    await user.click(tlsSwitch());

    expect(getSettings().provider_credentials?.rhoai?.ssl_verify).toBe("false");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Certificate verification is disabled.",
    );
  });

  it("submits the embeddings endpoint, limit and CA path that were typed", async () => {
    const { user, getSettings } = renderOnboarding("rhoai");
    await user.click(await screen.findByRole("button", { name: "Embeddings" }));
    await user.click(advancedToggle());

    await user.type(embeddingEndpoint(), "https://embed.example.com/v1");
    await user.type(concurrency(), "4");
    await user.type(caPath(), "/var/run/secrets/service-ca.crt");

    expect(getSettings().provider_credentials?.rhoai).toMatchObject({
      embedding_api_base: "https://embed.example.com/v1",
      embedding_max_concurrency: "4",
      ssl_verify: "/var/run/secrets/service-ca.crt",
    });
  });

  it("submits nothing for TLS while verification stays at its default", async () => {
    const { user, getSettings } = renderOnboarding("rhoai");
    await user.type(
      await screen.findByLabelText(/Chat endpoint/),
      "https://chat.example.com/v1",
    );

    expect(getSettings().provider_credentials?.rhoai).toEqual({
      api_base: "https://chat.example.com/v1",
    });
  });

  it.each([
    [
      "an embeddings endpoint",
      { embedding_api_base: "https://embed.example.com/v1" },
      { embeddings: "true", advanced: "false" },
    ],
    [
      "a concurrency limit",
      { embedding_max_concurrency: "4" },
      { embeddings: "true", advanced: "false" },
    ],
    [
      "a disabled TLS setting",
      { ssl_verify: "false" },
      { embeddings: "false", advanced: "true" },
    ],
    [
      "a CA path",
      { ssl_verify: "/var/run/secrets/service-ca.crt" },
      { embeddings: "false", advanced: "true" },
    ],
    [
      "the default TLS setting",
      { ssl_verify: "true" },
      { embeddings: "false", advanced: "false" },
    ],
  ])("opens only the section holding %s when saved", async (_name, saved, expanded) => {
    renderOnboarding("rhoai", false, savedRhoai(saved));

    await screen.findByLabelText(/Chat endpoint/);
    expect(embeddingsToggle()).toHaveAttribute(
      "aria-expanded",
      expanded.embeddings,
    );
    expect(advancedToggle()).toHaveAttribute(
      "aria-expanded",
      expanded.advanced,
    );
  });

  it("shows saved values in their fields", async () => {
    renderOnboarding(
      "rhoai",
      false,
      savedRhoai({
        embedding_api_base: "https://embed.example.com/v1",
        embedding_max_concurrency: "4",
        ssl_verify: "/var/run/secrets/service-ca.crt",
      }),
    );

    await screen.findByRole("switch", { name: "Verify TLS certificates" });
    expect(embeddingEndpoint()).toHaveValue("https://embed.example.com/v1");
    expect(concurrency()).toHaveValue("4");
    expect(caPath()).toHaveValue("/var/run/secrets/service-ca.crt");
    expect(tlsSwitch()).toBeChecked();
  });

  it("removes a saved false once verification is switched back on", async () => {
    const { user, getSettings } = renderOnboarding(
      "rhoai",
      false,
      savedRhoai({ ssl_verify: "false" }),
    );
    const toggle = await screen.findByRole("switch", {
      name: "Verify TLS certificates",
    });
    expect(toggle).not.toBeChecked();
    expect(screen.getByRole("alert")).toBeInTheDocument();

    await user.click(toggle);

    // Blank means "verify" to the backend, so the saved false is removed
    // rather than overwritten with "true".
    expect(getSettings().provider_credential_removals?.rhoai).toEqual([
      "ssl_verify",
    ]);
    expect(
      getSettings().provider_credentials?.rhoai?.ssl_verify,
    ).toBeUndefined();
  });

  it("asks for the token again only while the TLS setting differs from the saved one", async () => {
    const { user, getBlocker } = renderOnboarding(
      "rhoai",
      false,
      savedRhoai({}, ["api_key"]),
      [
        http.post("/api/models/rhoai/discover", () =>
          HttpResponse.json({ models: null, embedding_models: null }),
        ),
      ],
    );
    await user.click(
      await screen.findByRole("button", { name: "Advanced settings" }),
    );
    expect(getBlocker()).toBeNull();

    await user.click(tlsSwitch());
    await waitFor(() =>
      expect(getBlocker()).toBe(
        "Enter Token again: the endpoint or TLS setting changed.",
      ),
    );

    // Back on: blank again, exactly as saved, so the saved token still counts.
    await user.click(tlsSwitch());
    await waitFor(() => expect(getBlocker()).toBeNull());
    expect(
      screen.getByText(
        "A value is already saved. Leave this blank to keep it.",
      ),
    ).toBeInTheDocument();
  });
});
