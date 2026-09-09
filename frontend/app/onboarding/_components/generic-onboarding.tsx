import type { Dispatch, SetStateAction } from "react";
import { useMemo, useState } from "react";
import { useGetModelCatalogQuery } from "@/app/api/queries/useGetModelsQuery";
import { LabelInput } from "@/components/label-input";
import {
  onboardingCredentialFields,
  type SavedProvidersSnapshot,
  savedCredentialValuesForProvider,
  savedSecretFieldsForProvider,
} from "@/components/models/catalog-models";
import { getProviderChrome } from "@/components/models/model-helpers";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";
import { AdvancedOnboarding } from "./advanced";
import {
  AZURE_AUTH_GROUPS,
  GenericProviderCredentialFields,
} from "./generic-provider-credential-fields";

/**
 * Onboarding step for a provider with no hand-built component.
 *
 * The credential inputs come from the catalogue's field spec and the model list
 * from the catalogue itself, so a provider added to
 * `config/model_providers.yaml` gets a working onboarding tab with no frontend
 * change. Credentials are submitted through the generic `provider_credentials`
 * payload the onboarding endpoint already accepts.
 */
export function GenericOnboarding({
  provider,
  displayName,
  setSettings,
  isEmbedding = false,
  providers,
}: {
  provider: string;
  displayName?: string;
  setSettings: Dispatch<SetStateAction<OnboardingVariables>>;
  isEmbedding?: boolean;
  providers?: SavedProvidersSnapshot;
}) {
  const { data: catalog } = useGetModelCatalogQuery();
  const chrome = getProviderChrome(provider, displayName);
  const Logo = chrome.logo;

  const fields = useMemo(
    () => onboardingCredentialFields(catalog, provider),
    [catalog, provider],
  );
  const savedSecrets = useMemo(
    () => new Set(savedSecretFieldsForProvider(providers, provider)),
    [providers, provider],
  );
  const savedValues = useMemo(
    () => savedCredentialValuesForProvider(providers, provider),
    [providers, provider],
  );

  const [credentials, setCredentials] = useState<Record<string, string>>({});
  const [model, setModel] = useState("");
  const [azureAuthMethod, setAzureAuthMethod] = useState(
    providers?.custom?.[provider]?.auth_method ?? "api_key",
  );
  const [onPremAuthMethod, setOnPremAuthMethod] = useState(
    providers?.custom?.[provider]?.auth_method ?? "username_api_key",
  );

  const syncParentSettings = (
    nextCredentials: Record<string, string>,
    nextModel: string,
  ) => {
    const submitted: Record<string, string> = {};
    const activeAzureFields = new Set([
      "api_base",
      "api_version",
      ...(AZURE_AUTH_GROUPS.find((group) => group.key === azureAuthMethod)
        ?.fields ?? []),
    ]);
    const activeOnPremFields = new Set([
      "api_base",
      "space_id",
      "project_id",
      ...(onPremAuthMethod === "zen_api_key"
        ? ["zen_api_key"]
        : ["username", "api_key"]),
    ]);
    for (const [key, value] of Object.entries(nextCredentials)) {
      if (provider === "azure" && !activeAzureFields.has(key)) continue;
      if (provider === "watsonx_onprem" && !activeOnPremFields.has(key))
        continue;
      const trimmed = (value ?? "").trim();
      if (trimmed !== "") {
        submitted[key] = trimmed;
      }
    }

    setSettings((prev) => ({
      ...prev,
      ...(isEmbedding
        ? { embedding_provider: provider, embedding_model: nextModel }
        : { llm_provider: provider, llm_model: nextModel }),
      provider_credentials: Object.keys(submitted).length
        ? { ...prev.provider_credentials, [provider]: submitted }
        : prev.provider_credentials,
      ...(provider === "azure"
        ? {
            provider_auth_methods: {
              ...prev.provider_auth_methods,
              azure: azureAuthMethod,
            },
          }
        : {}),
      ...(provider === "watsonx_onprem"
        ? {
            provider_auth_methods: {
              ...prev.provider_auth_methods,
              watsonx_onprem: onPremAuthMethod,
            },
          }
        : {}),
    }));
  };

  // Seed the non-secret fields from what is already saved, once per provider.
  const [seededFor, setSeededFor] = useState<string | undefined>();
  if (seededFor !== provider) {
    setSeededFor(provider);
    setCredentials(savedValues);
    syncParentSettings(savedValues, model);
  }

  const catalogEntry = catalog?.providers?.find(
    (entry) => entry.key === provider,
  );
  const models = useMemo(() => {
    const entries = isEmbedding
      ? (catalogEntry?.embedding_models ?? [])
      : (catalogEntry?.models ?? []);
    return entries.map((entry) => ({
      value: entry.model,
      label: entry.model,
    }));
  }, [catalogEntry, isEmbedding]);

  // Default to the first model the catalogue lists for this provider.
  const [prevModels, setPrevModels] = useState<typeof models | undefined>();
  if (models !== prevModels) {
    setPrevModels(models);
    if (!model && models.length > 0) {
      const defaultModel = models[0].value;
      setModel(defaultModel);
      syncParentSettings(credentials, defaultModel);
    }
  }

  const handleCredentialChange = (fieldKey: string, newValue: string) => {
    const nextCredentials = { ...credentials, [fieldKey]: newValue };
    setCredentials(nextCredentials);
    syncParentSettings(nextCredentials, model);
  };

  const handleModelChange = (newModel: string) => {
    setModel(newModel);
    syncParentSettings(credentials, newModel);
  };

  const handleAzureAuthMethodChange = (method: string) => {
    setAzureAuthMethod(method);
    // The closure still holds the previous method during this event; submit
    // just the new method's fields explicitly so inactive values stay local.
    const active = new Set([
      "api_base",
      "api_version",
      ...(AZURE_AUTH_GROUPS.find((group) => group.key === method)?.fields ??
        []),
    ]);
    const selected = Object.fromEntries(
      Object.entries(credentials).filter(([key]) => active.has(key)),
    );
    setSettings((prev) => ({
      ...prev,
      provider_credentials: { ...prev.provider_credentials, azure: selected },
      provider_auth_methods: { ...prev.provider_auth_methods, azure: method },
    }));
  };

  const handleOnPremAuthMethodChange = (method: string) => {
    setOnPremAuthMethod(method);
    const active = new Set([
      "api_base",
      "space_id",
      "project_id",
      ...(method === "zen_api_key" ? ["zen_api_key"] : ["username", "api_key"]),
    ]);
    const selected = Object.fromEntries(
      Object.entries(credentials).filter(([key]) => active.has(key)),
    );
    setSettings((prev) => ({
      ...prev,
      provider_credentials: {
        ...prev.provider_credentials,
        watsonx_onprem: selected,
      },
      provider_auth_methods: {
        ...prev.provider_auth_methods,
        watsonx_onprem: method,
      },
    }));
  };

  const renderField = (field: (typeof fields)[number]) => {
    const isSecret =
      field.field_type === "password" || field.field_type === "textarea";
    const hasSaved = isSecret && savedSecrets.has(field.key);
    return (
      <div key={field.key} className="space-y-1">
        <LabelInput
          label={field.label}
          helperText={field.tooltip ?? ""}
          id={`onboarding-${provider}-${field.key}`}
          type={field.field_type === "password" ? "password" : "text"}
          required={field.required && !hasSaved}
          placeholder={
            hasSaved ? "•••••••••" : (field.placeholder ?? undefined)
          }
          value={credentials[field.key] ?? ""}
          onChange={(e) => handleCredentialChange(field.key, e.target.value)}
        />
        {hasSaved && (
          <p className="text-mmd text-muted-foreground">
            A value is already saved. Leave this blank to keep it.
          </p>
        )}
      </div>
    );
  };

  return (
    <>
      <div className="space-y-5">
        <GenericProviderCredentialFields
          provider={provider}
          fields={fields}
          azureAuthMethod={azureAuthMethod}
          onPremAuthMethod={onPremAuthMethod}
          onAzureAuthMethodChange={handleAzureAuthMethodChange}
          onOnPremAuthMethodChange={handleOnPremAuthMethodChange}
          renderField={renderField}
        />
        {models.length === 0 && (
          <p className="text-mmd text-muted-foreground">
            {chrome.name} publishes no {isEmbedding ? "embedding" : "language"}{" "}
            models in the catalogue. Pick a different provider for this step.
          </p>
        )}
      </div>
      <AdvancedOnboarding
        icon={<Logo className="w-4 h-4" />}
        languageModels={isEmbedding ? undefined : models}
        embeddingModels={isEmbedding ? models : undefined}
        languageModel={isEmbedding ? undefined : model}
        embeddingModel={isEmbedding ? model : undefined}
        setLanguageModel={isEmbedding ? undefined : handleModelChange}
        setEmbeddingModel={isEmbedding ? handleModelChange : undefined}
      />
    </>
  );
}
