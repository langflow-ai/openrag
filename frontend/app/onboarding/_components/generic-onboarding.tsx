import {
  type Dispatch,
  type SetStateAction,
  useMemo,
  useRef,
  useState,
} from "react";
import { useGetModelCatalogQuery } from "@/app/api/queries/useGetModelsQuery";
import {
  onboardingCredentialFields,
  type SavedProvidersSnapshot,
  savedCredentialValuesForProvider,
  savedSecretFieldsForProvider,
} from "@/components/models/catalog-models";
import {
  getProviderChrome,
  requiresExplicitModelSelection,
} from "@/components/models/model-helpers";
import {
  activeCredentialKeys,
  authMethodCredentialKeys,
  clearedSavedCredentialKeys,
  credentialTargetChanged,
  rhoaiSectionsOpenByDefault,
} from "@/components/models/provider-credentials";
import {
  RhoaiTlsSettings,
  WatsonxTlsSettings,
} from "@/components/models/tls-verification-settings";
import { WatsonxSpaceSelect } from "@/components/models/watsonx-space-select";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";
import { AdvancedOnboarding } from "./advanced";
import {
  GenericCredentialInput,
  GenericProviderCredentialFields,
} from "./generic-provider-credential-fields";
import { useOnboardingCompletionBlocker } from "./use-onboarding-completion-blocker";
import { useOnboardingModelDiscovery } from "./use-onboarding-model-discovery";
import { useOnboardingModelSelection } from "./use-onboarding-model-selection";

/**
 * Onboarding step for a provider with no hand-built component.
 *
 * The credential inputs come from the catalogue's field spec and the model list
 * from the catalogue itself, so a provider added to
 * `config/model_providers.yaml` gets a working onboarding tab with no frontend
 * change. Credentials are submitted through the generic `provider_credentials`
 * payload the onboarding endpoint already accepts.
 *
 * `onCompletionBlockerChange` reports why Submit must wait (a saved secret to
 * re-enter for a changed endpoint), or `null` once nothing blocks it.
 */
export function GenericOnboarding({
  provider,
  displayName,
  setSettings,
  isEmbedding = false,
  providers,
  onCompletionBlockerChange,
}: {
  provider: string;
  displayName?: string;
  setSettings: Dispatch<SetStateAction<OnboardingVariables>>;
  isEmbedding?: boolean;
  providers?: SavedProvidersSnapshot;
  onCompletionBlockerChange?: (blocker: string | null) => void;
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
  // A saved secret belongs to the host it was saved for: once the endpoint or
  // TLS setting is edited — or a saved one cleared, which Submit sends as a
  // removal — it is neither offered for reuse nor sent anywhere, and the
  // backend refuses a Submit that leaves it blank.
  const targetChanged = credentialTargetChanged(credentials, savedCredentials);
  const reusableSecrets = useMemo(
    () => (targetChanged ? new Set<string>() : savedSecrets),
    [targetChanged, savedSecrets],
  );
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
    const active = activeCredentialKeys(
      provider,
      azureAuthMethod,
      onPremAuthMethod,
    );
    for (const [key, value] of Object.entries(nextCredentials)) {
      if (active && !active.has(key)) continue;
      const trimmed = (value ?? "").trim();
      if (trimmed !== "") submitted[key] = trimmed;
    }
    const removals = clearedSavedCredentialKeys(
      nextCredentials,
      savedCredentials,
      savedSecrets,
      active,
    );
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

  // Memoised: model discovery filters by this set, and a fresh one each render
  // would redo that work every render.
  const activeKeys = useMemo(
    () => activeCredentialKeys(provider, azureAuthMethod, onPremAuthMethod),
    [provider, azureAuthMethod, onPremAuthMethod],
  );

  const reenterKeys = useOnboardingCompletionBlocker({
    credentials,
    savedSecrets,
    activeKeys,
    targetChanged,
    fields,
    onCompletionBlockerChange,
  });

  const {
    discovers,
    models,
    status: discoveryStatus,
    inFlight: discoveryInFlight,
  } = useOnboardingModelDiscovery({
    catalog,
    provider,
    isEmbedding,
    fields,
    credentials,
    activeKeys,
    requiredKeys: authMethodCredentialKeys(
      provider,
      azureAuthMethod,
      onPremAuthMethod,
    ),
    // Every method's, unfiltered: discovery applies the chosen method's keys
    // after debouncing what was typed, so a method switch is not debounced.
    clearedKeys: clearedSavedCredentialKeys(
      credentials,
      savedCredentials,
      savedSecrets,
      null,
    ),
    savedSecrets: reusableSecrets,
    authMethod: provider === "watsonx_onprem" ? onPremAuthMethod : undefined,
  });

  const { model, pickModel } = useOnboardingModelSelection({
    provider,
    models,
    inFlight: discoveryInFlight,
    onModelChange: (nextModel) => syncParentSettings(credentials, nextModel),
  });

  const handleCredentialChange = (fieldKey: string, newValue: string) => {
    const nextCredentials = { ...credentials, [fieldKey]: newValue };
    setCredentials(nextCredentials);
    syncParentSettings(nextCredentials, model);
  };

  const handleAuthMethodChange = (
    target: "azure" | "watsonx_onprem",
    method: string,
  ) => {
    const isAzure = target === "azure";
    (isAzure ? setAzureAuthMethod : setOnPremAuthMethod)(method);
    // The closure still holds the previous method during this event; submit
    // just the new method's fields explicitly so inactive values stay local.
    const active = activeCredentialKeys(
      target,
      isAzure ? method : azureAuthMethod,
      isAzure ? onPremAuthMethod : method,
    );
    const selected = Object.fromEntries(
      Object.entries(credentials).filter(([key]) => active?.has(key)),
    );
    setSettings((prev) => ({
      ...prev,
      provider_credentials: {
        ...prev.provider_credentials,
        [target]: selected,
      },
      provider_auth_methods: {
        ...prev.provider_auth_methods,
        [target]: method,
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
          hasSavedApiKey={reusableSecrets.has("api_key")}
          hasSavedZenApiKey={reusableSecrets.has("zen_api_key")}
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

    if (provider === "rhoai" && field.key === "ssl_verify") {
      return (
        <RhoaiTlsSettings
          key={field.key}
          idPrefix={`onboarding-${provider}`}
          value={credentials.ssl_verify}
          onValueChange={(value) => handleCredentialChange("ssl_verify", value)}
        />
      );
    }

    return (
      <GenericCredentialInput
        key={field.key}
        field={field}
        id={`onboarding-${provider}-${field.key}`}
        value={credentials[field.key] ?? ""}
        hasSavedSecret={reusableSecrets.has(field.key)}
        needsReentry={reenterKeys.includes(field.key)}
        onChange={(value) => handleCredentialChange(field.key, value)}
      />
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
          rhoaiOpenByDefault={rhoaiSectionsOpenByDefault(savedCredentials, {
            isEmbedding,
          })}
          onAzureAuthMethodChange={(method) =>
            handleAuthMethodChange("azure", method)
          }
          onOnPremAuthMethodChange={(method) =>
            handleAuthMethodChange("watsonx_onprem", method)
          }
          renderField={renderField}
        />
        {discoveryStatus && (
          <p className="text-mmd text-muted-foreground" role="status">
            {discoveryStatus}
          </p>
        )}
        {models.length === 0 && !discovers && (
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
        setLanguageModel={isEmbedding ? undefined : pickModel}
        setEmbeddingModel={isEmbedding ? pickModel : undefined}
      />
    </>
  );
}
