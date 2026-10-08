import {
  type Dispatch,
  type SetStateAction,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useDiscoverProviderModelsQuery } from "@/app/api/queries/useDiscoverProviderModelsQuery";
import { useGetModelCatalogQuery } from "@/app/api/queries/useGetModelsQuery";
import { LabelInput } from "@/components/label-input";
import {
  onboardingCredentialFields,
  providerCatalogOptions,
  providerDiscoversModels,
  type SavedProvidersSnapshot,
  savedCredentialValuesForProvider,
  savedSecretFieldsForProvider,
  withDiscoveredModels,
} from "@/components/models/catalog-models";
import {
  getProviderChrome,
  requiresExplicitModelSelection,
} from "@/components/models/model-helpers";
import { WatsonxSpaceSelect } from "@/components/models/watsonx-space-select";
import { WatsonxTlsSettings } from "@/components/models/watsonx-tls-settings";
import { useDebouncedValue } from "@/lib/debounce";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";
import { AdvancedOnboarding } from "./advanced";
import { GenericProviderCredentialFields } from "./generic-provider-credential-fields";
import { activeCredentialKeys } from "./generic-provider-credential-fields.helpers";

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
  const savedCredentials = useMemo(
    () => savedCredentialValuesForProvider(providers, provider),
    [providers, provider],
  );
  const savedSecrets = useMemo(
    () => new Set(savedSecretFieldsForProvider(providers, provider)),
    [providers, provider],
  );

  const [credentials, setCredentials] =
    useState<Record<string, string>>(savedCredentials);
  const [model, setModel] = useState("");
  const [azureAuthMethod, setAzureAuthMethod] = useState(
    providers?.custom?.[provider]?.auth_method ?? "api_key",
  );
  const [onPremAuthMethod, setOnPremAuthMethod] = useState(
    providers?.custom?.[provider]?.auth_method ?? "username_api_key",
  );

  // Stable ref so syncParentSettings can be called from effects without
  // needing to be listed in deps (it only reads provider/isEmbedding which
  // are stable within a single render of this component).
  const setSettingsRef = useRef(setSettings);
  setSettingsRef.current = setSettings;

  const syncParentSettings = (
    nextCredentials: Record<string, string>,
    nextModel: string,
  ) => {
    const submitted: Record<string, string> = {};
    const removals: string[] = [];
    const active = activeCredentialKeys(
      provider,
      azureAuthMethod,
      onPremAuthMethod,
    );
    for (const [key, value] of Object.entries(nextCredentials)) {
      if (active && !active.has(key)) continue;
      const trimmed = (value ?? "").trim();
      if (trimmed !== "") {
        submitted[key] = trimmed;
      } else if (!savedSecrets.has(key) && savedCredentials[key]) {
        removals.push(key);
      }
    }
    setSettingsRef.current((prev) => {
      const providerCredentialRemovals = {
        ...prev.provider_credential_removals,
      };
      if (removals.length > 0) {
        providerCredentialRemovals[provider] = removals;
      } else {
        delete providerCredentialRemovals[provider];
      }

      return {
        ...prev,
        ...(isEmbedding
          ? { embedding_provider: provider, embedding_model: nextModel }
          : { llm_provider: provider, llm_model: nextModel }),
        provider_credentials: Object.keys(submitted).length
          ? { ...prev.provider_credentials, [provider]: submitted }
          : prev.provider_credentials,
        provider_credential_removals:
          Object.keys(providerCredentialRemovals).length > 0
            ? providerCredentialRemovals
            : undefined,
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
      };
    });
  };

  // A cluster-hosted provider serves whatever its operator deployed, and the
  // catalogue can only list it once credentials are saved. Ask the cluster
  // with what has been typed so far, so the picker offers what it serves
  // rather than the configured fallback.
  const discovers = providerDiscoversModels(catalog, provider);
  const active = activeCredentialKeys(
    provider,
    azureAuthMethod,
    onPremAuthMethod,
  );
  const typedCredentials: Record<string, string> = {};
  for (const [key, value] of Object.entries(credentials)) {
    const trimmed = (value ?? "").trim();
    if (trimmed && (!active || active.has(key)))
      typedCredentials[key] = trimmed;
  }
  // Debounced as a string: a fresh object each render would reset the timer.
  const discoveryKey = useDebouncedValue(JSON.stringify(typedCredentials), 500);
  const discoveryCredentials = useMemo(
    () => JSON.parse(discoveryKey) as Record<string, string>,
    [discoveryKey],
  );
  const hasValue = (key: string) =>
    Boolean(discoveryCredentials[key]) || savedSecrets.has(key);
  const activeFields = fields.filter(
    (field) => !active || active.has(field.key),
  );
  const discoveryReady =
    discovers &&
    activeFields.every((field) => !field.required || hasValue(field.key)) &&
    activeFields
      .filter((field) => field.field_type === "password")
      .every((field) => hasValue(field.key));
  const discovery = useDiscoverProviderModelsQuery(
    {
      provider,
      credentials: discoveryCredentials,
      authMethod: provider === "watsonx_onprem" ? onPremAuthMethod : undefined,
    },
    { enabled: discoveryReady },
  );
  const discovered = discoveryReady ? discovery.data : undefined;
  const discoveredHalf = isEmbedding
    ? discovered?.embedding_models
    : discovered?.models;

  const models = useMemo(
    () =>
      providerCatalogOptions(
        withDiscoveredModels(catalog, provider, discovered),
        provider,
        isEmbedding ? "embedding" : "language",
      ),
    [catalog, provider, isEmbedding, discovered],
  );

  // Azure's catalogue lists model families, not this customer's deployments,
  // so require an explicit choice. Other providers still default to the
  // highest-ranked model when the catalogue loads or provider changes.
  const defaultedModelRef = useRef<string | undefined>(undefined);
  // Whether the current model was picked here rather than by the user. An
  // automatic choice follows the list: when discovery replaces the configured
  // fallback, a model the cluster does not serve must not stay selected.
  const autoSelectedRef = useRef(false);
  useEffect(() => {
    if (requiresExplicitModelSelection(provider) || models.length === 0) return;
    if (model) {
      if (
        !autoSelectedRef.current ||
        models.some((option) => option.value === model)
      )
        return;
      const nextModel = models[0].value;
      setModel(nextModel);
      syncParentSettings(credentials, nextModel);
      return;
    }
    const defaultModel = models[0].value;
    // Only set once per provider so switching back doesn't re-default.
    if (defaultedModelRef.current === `${provider}:${defaultModel}`) return;
    defaultedModelRef.current = `${provider}:${defaultModel}`;
    autoSelectedRef.current = true;
    setModel(defaultModel);
    syncParentSettings(credentials, defaultModel);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [models, model, provider]);

  const handleCredentialChange = (fieldKey: string, newValue: string) => {
    const nextCredentials = { ...credentials, [fieldKey]: newValue };
    setCredentials(nextCredentials);
    syncParentSettings(nextCredentials, model);
  };

  const handleModelChange = (newModel: string) => {
    autoSelectedRef.current = false;
    setModel(newModel);
    syncParentSettings(credentials, newModel);
  };

  const kindLabel = isEmbedding ? "embedding" : "language";
  let discoveryStatus: string | null = null;
  if (discoveryReady) {
    if (discovery.isFetching) {
      discoveryStatus = "Checking which models the cluster serves…";
    } else if (discovery.isError || (discovery.isSuccess && !discoveredHalf)) {
      discoveryStatus = `Couldn't list ${kindLabel} models from the cluster — showing configured defaults. Type a model ID to use another.`;
    } else if (discoveredHalf && discoveredHalf.length > 0) {
      discoveryStatus = `Showing ${discoveredHalf.length} ${kindLabel} ${
        discoveredHalf.length === 1 ? "model" : "models"
      } served by the cluster.`;
    }
  }

  const handleAzureAuthMethodChange = (method: string) => {
    setAzureAuthMethod(method);
    // The closure still holds the previous method during this event; submit
    // just the new method's fields explicitly so inactive values stay local.
    const active = activeCredentialKeys("azure", method, onPremAuthMethod);
    const selected = Object.fromEntries(
      Object.entries(credentials).filter(([key]) => active?.has(key)),
    );
    setSettings((prev) => ({
      ...prev,
      provider_credentials: { ...prev.provider_credentials, azure: selected },
      provider_auth_methods: { ...prev.provider_auth_methods, azure: method },
    }));
  };

  const handleOnPremAuthMethodChange = (method: string) => {
    setOnPremAuthMethod(method);
    const active = activeCredentialKeys(
      "watsonx_onprem",
      azureAuthMethod,
      method,
    );
    const selected = Object.fromEntries(
      Object.entries(credentials).filter(([key]) => active?.has(key)),
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
    if (provider === "watsonx_onprem" && field.key === "space_id") {
      return (
        <WatsonxSpaceSelect
          key={field.key}
          idPrefix={`onboarding-${provider}`}
          credentials={credentials}
          authMethod={onPremAuthMethod}
          hasSavedApiKey={savedSecrets.has("api_key")}
          hasSavedZenApiKey={savedSecrets.has("zen_api_key")}
          value={credentials.space_id}
          onValueChange={(value) => handleCredentialChange("space_id", value)}
          helperText={field.tooltip ?? undefined}
        />
      );
    }

    if (provider === "watsonx_onprem" && field.key === "ssl_verify") {
      return (
        <WatsonxTlsSettings
          key={field.key}
          idPrefix={`onboarding-${provider}`}
          value={credentials.ssl_verify}
          onValueChange={(value) => handleCredentialChange("ssl_verify", value)}
        />
      );
    }

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
        {discoveryStatus && (
          <p className="text-mmd text-muted-foreground" role="status">
            {discoveryStatus}
          </p>
        )}
        {models.length === 0 && (
          <p className="text-mmd text-muted-foreground">
            {chrome.name} publishes no {isEmbedding ? "embedding" : "language"}{" "}
            models in the catalogue. Pick a different provider for this step.
          </p>
        )}
      </div>
      <AdvancedOnboarding
        icon={<Logo className="w-4 h-4" />}
        searchPlaceholder={
          requiresExplicitModelSelection(provider)
            ? "Search models or type Azure deployment name"
            : undefined
        }
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
