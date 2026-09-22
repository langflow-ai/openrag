import { HttpResponse, http } from "msw";
import type { Dispatch, SetStateAction } from "react";
import { describe, expect, it } from "vitest";
import type { OnboardingVariables } from "@/app/api/mutations/useOnboardingMutation";
import type { SavedProvidersSnapshot } from "@/components/models/catalog-models";
import { renderWithProviders, screen, userEvent } from "@/test-utils/render";
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
  ],
};

function renderOnboarding(
  provider: string,
  isEmbedding = false,
  savedProviders?: SavedProvidersSnapshot,
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

    expect(verifyTls).not.toBeChecked();
    expect(
      screen.getByText(/Certificate verification is disabled/),
    ).toBeVisible();

    await user.click(verifyTls);
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
