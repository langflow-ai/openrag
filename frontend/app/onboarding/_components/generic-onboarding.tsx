import {
  type Dispatch,
  type SetStateAction,
  useEffect,
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
} from "@/app/settings/_helpers/catalog-models";
import { getProviderChrome } from "@/app/settings/_helpers/model-helpers";
import { LabelInput } from "@/components/label-input";
import type { OnboardingVariables } from "../../api/mutations/useOnboardingMutation";
import { AdvancedOnboarding } from "./advanced";

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
    for (const [key, value] of Object.entries(nextCredentials)) {
      const trimmed = (value ?? "").trim();
      if (trimmed !== "") {
        submitted[key] = trimmed;
      }
    }
    setSettingsRef.current((prev) => ({
      ...prev,
      ...(isEmbedding
        ? { embedding_provider: provider, embedding_model: nextModel }
        : { llm_provider: provider, llm_model: nextModel }),
      provider_credentials: Object.keys(submitted).length
        ? { ...prev.provider_credentials, [provider]: submitted }
        : prev.provider_credentials,
    }));
  };

  // Seed credentials and parent settings when provider changes.
  // useEffect ensures this runs after render, not during it.
  const seededForRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (seededForRef.current === provider) return;
    seededForRef.current = provider;
    setCredentials(savedValues);
    syncParentSettings(savedValues, model);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider, savedValues]);

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

  // Default to the first model when the catalogue loads or provider changes.
  const defaultedModelRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (model || models.length === 0) return;
    const defaultModel = models[0].value;
    // Only set once per provider so switching back doesn't re-default.
    if (defaultedModelRef.current === `${provider}:${defaultModel}`) return;
    defaultedModelRef.current = `${provider}:${defaultModel}`;
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
    setModel(newModel);
    syncParentSettings(credentials, newModel);
  };

  return (
    <>
      <div className="space-y-5">
        {fields.map((field) => {
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
                onChange={(e) =>
                  handleCredentialChange(field.key, e.target.value)
                }
              />
              {hasSaved && (
                <p className="text-mmd text-muted-foreground">
                  A value is already saved. Leave this blank to keep it.
                </p>
              )}
            </div>
          );
        })}
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
