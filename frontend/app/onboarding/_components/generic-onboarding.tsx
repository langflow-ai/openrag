import type { Dispatch, SetStateAction } from "react";
import { useEffect, useMemo, useState } from "react";
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

  // Seed the non-secret fields from what is already saved, once per provider.
  const [seededFor, setSeededFor] = useState<string | undefined>();
  if (seededFor !== provider) {
    setSeededFor(provider);
    setCredentials(savedValues);
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

  const [model, setModel] = useState("");

  // Default to the first model the catalogue lists for this provider.
  const [prevModels, setPrevModels] = useState<typeof models | undefined>();
  if (models !== prevModels) {
    setPrevModels(models);
    if (!model && models.length > 0) {
      setModel(models[0].value);
    }
  }

  useEffect(() => {
    const submitted = Object.fromEntries(
      Object.entries(credentials)
        .map(([key, value]) => [key, (value ?? "").trim()])
        .filter(([, value]) => value !== ""),
    );

    setSettings((prev) => ({
      ...prev,
      ...(isEmbedding
        ? { embedding_provider: provider, embedding_model: model }
        : { llm_provider: provider, llm_model: model }),
      provider_credentials: Object.keys(submitted).length
        ? { ...prev.provider_credentials, [provider]: submitted }
        : prev.provider_credentials,
    }));
  }, [credentials, model, provider, isEmbedding, setSettings]);

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
                  setCredentials((prev) => ({
                    ...prev,
                    [field.key]: e.target.value,
                  }))
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
        setLanguageModel={isEmbedding ? undefined : setModel}
        setEmbeddingModel={isEmbedding ? setModel : undefined}
      />
    </>
  );
}
