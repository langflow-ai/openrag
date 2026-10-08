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
) {
  let settings: OnboardingVariables = {};
  const setSettings: Dispatch<SetStateAction<OnboardingVariables>> = (next) => {
    settings = typeof next === "function" ? next(settings) : next;
  };
  const user = userEvent.setup();
  renderWithProviders(
    <GenericOnboarding
      provider={provider}
      isEmbedding={isEmbedding}
      setSettings={setSettings}
      providers={savedProviders}
    />,
    {
      providers: ["tooltip"],
      handlers: [
        http.get("/api/models/catalog", () => HttpResponse.json(catalog)),
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
  return { user, getSettings: () => settings };
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

  function discoverHandler(
    response: () => Response,
    requests: Array<{ credentials: Record<string, string> }> = [],
  ) {
    return http.post("/api/models/rhoai/discover", async ({ request }) => {
      requests.push(
        (await request.json()) as { credentials: Record<string, string> },
      );
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
    const requests: Array<{ credentials: Record<string, string> }> = [];
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

    await user.click(screen.getByRole("combobox", { name: "Language model" }));
    expect(
      await screen.findByRole("option", { name: "gpt-oss-120b" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("option", { name: "granite-3.3-2b-instruct" }),
    ).not.toBeInTheDocument();
  });

  it("uses the embedding endpoint's listing for the embedding picker", async () => {
    const { user, getSettings } = renderOnboarding("rhoai", true, undefined, [
      discoverHandler(served),
    ]);

    await typeCredentials(user);

    await screen.findByText(
      "Showing 1 embedding model served by the cluster.",
      {},
      DISCOVERY_TIMEOUT,
    );
    expect(getSettings().embedding_model).toBe("nomic-embed-text");
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
