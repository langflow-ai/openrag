"use client";

import { type Dispatch, type SetStateAction, useEffect, useState } from "react";
import type { OnboardingVariables } from "@/app/api/mutations/useOnboardingMutation";
import {
  type ModelCatalogResponse,
  type ModelsResponse,
  useGetAnthropicModelsQuery,
  useGetIBMModelsQuery,
  useGetOllamaModelsQuery,
  useGetOpenAIModelsQuery,
} from "@/app/api/queries/useGetModelsQuery";
import {
  type CatalogCredentialField,
  onboardingCredentialFields,
  type SettingsCatalogProvider,
} from "@/app/settings/_helpers/catalog-models";
import { LabelInput } from "@/components/label-input";
import { LabelWrapper } from "@/components/label-wrapper";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useDebouncedValue } from "@/lib/debounce";
import { useUpdateSettings } from "../_hooks/useUpdateSettings";
import { ModelSelector } from "./model-selector";

const WATSONX_ENDPOINTS = [
  "https://us-south.ml.cloud.ibm.com",
  "https://eu-de.ml.cloud.ibm.com",
  "https://eu-gb.ml.cloud.ibm.com",
  "https://au-syd.ml.cloud.ibm.com",
  "https://jp-tok.ml.cloud.ibm.com",
  "https://ca-tor.ml.cloud.ibm.com",
];

const ENV_SWITCH_LABEL: Record<
  Exclude<SettingsCatalogProvider, "ollama">,
  { label: string; missing: string }
> = {
  openai: {
    label: "Use environment OpenAI API key",
    missing: "OpenAI API key not detected in the environment.",
  },
  anthropic: {
    label: "Use environment Anthropic API key",
    missing: "Anthropic API key not detected in the environment.",
  },
  watsonx: {
    label: "Use environment watsonx API key",
    missing: "watsonx API key not detected in the environment.",
  },
};

function testIdFor(key: string): string {
  if (key === "api_key") return "api-key";
  if (key === "api_base") return "api-endpoint";
  if (key === "project_id") return "project-id";
  return key;
}

function stringOptions(field: CatalogCredentialField): string[] | undefined {
  if (!Array.isArray(field.options)) return undefined;
  const options = field.options.filter(
    (entry): entry is string => typeof entry === "string",
  );
  return options.length > 0 ? options : undefined;
}

function initialValues(
  provider: SettingsCatalogProvider,
  fields: CatalogCredentialField[],
  alreadyConfigured: boolean,
  existingEndpoint?: string,
  existingProjectId?: string,
): Record<string, string> {
  const values: Record<string, string> = {};
  for (const field of fields) {
    if (alreadyConfigured) {
      values[field.key] = "";
      continue;
    }
    if (field.key === "api_base" && existingEndpoint) {
      values[field.key] = existingEndpoint;
    } else if (field.key === "project_id" && existingProjectId) {
      values[field.key] = existingProjectId;
    } else if (typeof field.default_value === "string" && field.default_value) {
      values[field.key] = field.default_value;
    } else if (field.key === "api_base" && provider === "ollama") {
      values[field.key] = "http://localhost:11434";
    } else if (field.key === "api_base" && provider === "watsonx") {
      values[field.key] = WATSONX_ENDPOINTS[0];
    } else {
      values[field.key] = "";
    }
  }
  return values;
}

export interface CredentialStatus {
  ready: boolean;
  isValidating: boolean;
  hasError: boolean;
}

interface OnboardingCredentialFieldsProps {
  provider: SettingsCatalogProvider;
  catalog: ModelCatalogResponse | undefined;
  isEmbedding: boolean;
  hasEnvApiKey: boolean;
  alreadyConfigured: boolean;
  existingEndpoint?: string;
  existingProjectId?: string;
  setSettings: Dispatch<SetStateAction<OnboardingVariables>>;
  onStatusChange: (status: CredentialStatus) => void;
  onLiveModelsChange: (data: ModelsResponse | undefined) => void;
}

export function OnboardingCredentialFields({
  provider,
  catalog,
  isEmbedding,
  hasEnvApiKey,
  alreadyConfigured,
  existingEndpoint,
  existingProjectId,
  setSettings,
  onStatusChange,
  onLiveModelsChange,
}: OnboardingCredentialFieldsProps) {
  const fields = onboardingCredentialFields(catalog, provider);
  const hasApiKeyField = fields.some((field) => field.key === "api_key");

  const [getFromEnv, setGetFromEnv] = useState(
    hasApiKeyField && hasEnvApiKey && !alreadyConfigured,
  );
  const [prevHasEnvApiKey, setPrevHasEnvApiKey] = useState(hasEnvApiKey);
  if (hasEnvApiKey !== prevHasEnvApiKey) {
    setPrevHasEnvApiKey(hasEnvApiKey);
    if (hasApiKeyField && hasEnvApiKey && !alreadyConfigured) {
      setGetFromEnv(true);
    }
  }

  const [values, setValues] = useState<Record<string, string>>(() =>
    initialValues(
      provider,
      fields,
      alreadyConfigured,
      existingEndpoint,
      existingProjectId,
    ),
  );
  const [fieldsKey, setFieldsKey] = useState(
    fields.map((f) => f.key).join(","),
  );
  const nextFieldsKey = fields.map((f) => f.key).join(",");
  if (nextFieldsKey !== fieldsKey) {
    setFieldsKey(nextFieldsKey);
    setValues(
      initialValues(
        provider,
        fields,
        alreadyConfigured,
        existingEndpoint,
        existingProjectId,
      ),
    );
  }

  const apiKey = values.api_key ?? "";
  const endpoint = values.api_base ?? "";
  const projectId = values.project_id ?? "";
  const debouncedApiKey = useDebouncedValue(apiKey, 500);
  const debouncedEndpoint = useDebouncedValue(endpoint, 500);
  const debouncedProjectId = useDebouncedValue(projectId, 500);

  const openaiModels = useGetOpenAIModelsQuery(
    getFromEnv
      ? { useEnvKey: true }
      : debouncedApiKey
        ? { apiKey: debouncedApiKey, useEnvKey: false }
        : undefined,
    {
      enabled:
        provider === "openai" &&
        (getFromEnv || alreadyConfigured || debouncedApiKey !== ""),
    },
  );
  const anthropicModels = useGetAnthropicModelsQuery(
    getFromEnv
      ? { useEnvKey: true }
      : debouncedApiKey
        ? { apiKey: debouncedApiKey, useEnvKey: false }
        : undefined,
    {
      enabled:
        provider === "anthropic" &&
        (getFromEnv || alreadyConfigured || debouncedApiKey !== ""),
    },
  );
  const ibmModels = useGetIBMModelsQuery(
    {
      endpoint: getFromEnv
        ? existingEndpoint || debouncedEndpoint || undefined
        : debouncedEndpoint || undefined,
      apiKey: getFromEnv ? undefined : debouncedApiKey || undefined,
      projectId: getFromEnv
        ? existingProjectId || debouncedProjectId || undefined
        : debouncedProjectId || undefined,
      useEnvKey: getFromEnv,
    },
    {
      enabled:
        provider === "watsonx" &&
        (getFromEnv
          ? !!(existingEndpoint || debouncedEndpoint) &&
            !!(existingProjectId || debouncedProjectId)
          : (!!debouncedEndpoint &&
              !!debouncedApiKey &&
              !!debouncedProjectId) ||
            alreadyConfigured),
    },
  );
  const ollamaModels = useGetOllamaModelsQuery(
    debouncedEndpoint ? { endpoint: debouncedEndpoint } : undefined,
    {
      enabled:
        provider === "ollama" && (!!debouncedEndpoint || alreadyConfigured),
    },
  );

  const active =
    provider === "openai"
      ? openaiModels
      : provider === "anthropic"
        ? anthropicModels
        : provider === "watsonx"
          ? ibmModels
          : ollamaModels;

  const isValidating = active.isLoading || active.isFetching;
  const showModelsError = !!active.error && !isValidating;
  const hasNoOllamaModels =
    provider === "ollama" &&
    !!ollamaModels.data &&
    !ollamaModels.data.language_models?.length &&
    !ollamaModels.data.embedding_models?.length;

  useEffect(() => {
    onLiveModelsChange(active.data);
  }, [active.data, onLiveModelsChange]);

  useEffect(() => {
    const keyReady =
      !hasApiKeyField || getFromEnv || alreadyConfigured || apiKey.length > 0;
    const endpointReady =
      provider !== "ollama" && provider !== "watsonx"
        ? true
        : alreadyConfigured || getFromEnv || endpoint.length > 0;
    const projectReady =
      provider !== "watsonx" ||
      alreadyConfigured ||
      getFromEnv ||
      projectId.length > 0;
    const filled = keyReady && endpointReady && projectReady;
    onStatusChange({
      ready: filled && (alreadyConfigured || !showModelsError),
      isValidating,
      hasError: showModelsError,
    });
  }, [
    alreadyConfigured,
    apiKey,
    endpoint,
    getFromEnv,
    hasApiKeyField,
    isValidating,
    onStatusChange,
    projectId,
    provider,
    showModelsError,
  ]);

  useUpdateSettings(
    provider,
    {
      apiKey: getFromEnv || alreadyConfigured ? undefined : apiKey,
      clearApiKey: getFromEnv,
      endpoint:
        getFromEnv && provider === "watsonx"
          ? existingEndpoint || endpoint
          : endpoint,
      projectId:
        getFromEnv && provider === "watsonx"
          ? existingProjectId || projectId
          : projectId,
    },
    setSettings,
    isEmbedding,
  );

  const setField = (key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const handleGetFromEnvChange = (fromEnv: boolean) => {
    setGetFromEnv(fromEnv);
    if (fromEnv) {
      setField("api_key", "");
      if (provider === "watsonx") {
        setField("api_base", existingEndpoint || WATSONX_ENDPOINTS[0]);
        setField("project_id", existingProjectId || "");
      }
    }
  };

  const envCopy =
    provider === "ollama" ? undefined : ENV_SWITCH_LABEL[provider];
  const locked = alreadyConfigured || getFromEnv;

  return (
    <div className="space-y-5">
      {hasApiKeyField && !alreadyConfigured && envCopy && (
        <LabelWrapper
          label={envCopy.label}
          id="get-api-key"
          description="Reuse the key from your environment config. Turn off to enter a different key."
          flex
        >
          <Tooltip>
            <TooltipTrigger asChild>
              <div>
                <Switch
                  checked={getFromEnv}
                  data-testid="get-from-env-switch"
                  onCheckedChange={handleGetFromEnvChange}
                  disabled={!hasEnvApiKey}
                />
              </div>
            </TooltipTrigger>
            {!hasEnvApiKey && (
              <TooltipContent>{envCopy.missing}</TooltipContent>
            )}
          </Tooltip>
        </LabelWrapper>
      )}

      {fields.map((field) => {
        if (field.key === "api_key" && getFromEnv && !alreadyConfigured) {
          return null;
        }
        const id = testIdFor(field.key);
        const value = values[field.key] ?? "";
        const fieldLocked =
          field.key === "api_key"
            ? alreadyConfigured
            : locked && field.key !== "api_key";
        const showKeyError = field.key === "api_key" && showModelsError;
        const helper = field.tooltip ?? "";
        const selectOptions =
          field.key === "api_base" && provider === "watsonx"
            ? WATSONX_ENDPOINTS
            : stringOptions(field);

        if (field.key === "api_base" && provider === "watsonx") {
          return (
            <LabelWrapper
              key={field.key}
              label={field.label}
              helperText={helper || "Base URL of the API"}
              id={id}
              required={field.required && !alreadyConfigured}
            >
              <div className="space-y-1">
                <ModelSelector
                  options={
                    alreadyConfigured
                      ? []
                      : WATSONX_ENDPOINTS.map((url, index) => ({
                          value: url,
                          label: url,
                          default: index === 0,
                        }))
                  }
                  value={value}
                  custom
                  data-testid={id}
                  onValueChange={
                    fieldLocked ? () => {} : (next) => setField(field.key, next)
                  }
                  disabled={fieldLocked}
                  searchPlaceholder="Search endpoint..."
                  noOptionsPlaceholder={
                    alreadyConfigured
                      ? "https://•••••••••••••••••••••••••••••••••••••••••"
                      : "No endpoints available"
                  }
                  placeholder="Select endpoint..."
                />
                {alreadyConfigured && (
                  <p className="text-mmd text-muted-foreground">
                    Reusing endpoint from model provider selection.
                  </p>
                )}
                {getFromEnv && !alreadyConfigured && (
                  <p className="text-mmd text-muted-foreground">
                    Reusing endpoint from environment config.
                  </p>
                )}
              </div>
            </LabelWrapper>
          );
        }

        if (selectOptions && field.field_type === "select") {
          return (
            <LabelWrapper
              key={field.key}
              id={id}
              label={field.label}
              helperText={helper || undefined}
              required={field.required && !alreadyConfigured}
            >
              <Select
                value={value}
                onValueChange={(next) => setField(field.key, next)}
                disabled={fieldLocked}
              >
                <SelectTrigger id={id} data-testid={id}>
                  <SelectValue
                    placeholder={field.placeholder ?? `Choose ${field.label}`}
                  />
                </SelectTrigger>
                <SelectContent>
                  {selectOptions.map((option) => (
                    <SelectItem key={option} value={option}>
                      {option}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </LabelWrapper>
          );
        }

        if (field.field_type === "password" || field.key === "api_key") {
          return (
            <div key={field.key} className="space-y-1">
              <LabelInput
                label={field.label}
                helperText={helper || "API key"}
                className={showKeyError ? "!border-destructive" : ""}
                id={id}
                type="password"
                required={field.required && !alreadyConfigured}
                placeholder={
                  alreadyConfigured
                    ? "•••••••••••••••••••••••••••••••••••••••••"
                    : (field.placeholder ?? undefined)
                }
                value={value}
                onChange={(event) => setField(field.key, event.target.value)}
                disabled={false}
              />
              {alreadyConfigured && (
                <p className="text-mmd text-muted-foreground">
                  Existing key detected. You can reuse it or enter a new one.
                </p>
              )}
              {field.key === "api_key" && isValidating && (
                <p className="text-mmd text-muted-foreground">
                  Validating API key...
                </p>
              )}
              {showKeyError && (
                <p className="text-mmd text-destructive">
                  {active.error?.message}
                </p>
              )}
            </div>
          );
        }

        return (
          <div key={field.key} className="space-y-1">
            {helper ? (
              <LabelInput
                label={field.label}
                helperText={helper}
                id={id}
                required={field.required && !alreadyConfigured}
                placeholder={
                  alreadyConfigured
                    ? "••••••••••••••••••••••••"
                    : (field.placeholder ?? undefined)
                }
                value={value}
                onChange={(event) => setField(field.key, event.target.value)}
                disabled={fieldLocked}
              />
            ) : (
              <LabelWrapper
                label={field.label}
                id={id}
                required={field.required && !alreadyConfigured}
              >
                <Input
                  id={id}
                  data-testid={id}
                  value={value}
                  placeholder={field.placeholder ?? undefined}
                  onChange={(event) => setField(field.key, event.target.value)}
                  disabled={fieldLocked}
                />
              </LabelWrapper>
            )}
            {alreadyConfigured && (
              <p className="text-mmd text-muted-foreground">
                Reusing this value from model provider selection.
              </p>
            )}
            {getFromEnv && !alreadyConfigured && field.key !== "api_key" && (
              <p className="text-mmd text-muted-foreground">
                Reusing this value from environment config.
              </p>
            )}
            {field.key === "api_base" &&
              provider === "ollama" &&
              isValidating && (
                <p className="text-mmd text-muted-foreground">
                  Connecting to Ollama server...
                </p>
              )}
            {field.key === "api_base" &&
              provider === "ollama" &&
              showModelsError && (
                <p className="text-mmd text-accent-amber-foreground">
                  {active.error?.message}
                </p>
              )}
            {field.key === "api_base" &&
              provider === "ollama" &&
              hasNoOllamaModels && (
                <p className="text-mmd text-accent-amber-foreground">
                  No models found. Install embedding and agent models on your
                  Ollama server.
                </p>
              )}
          </div>
        );
      })}

      {getFromEnv && isValidating && provider !== "ollama" && (
        <p className="text-mmd text-muted-foreground">
          Validating configuration...
        </p>
      )}
      {getFromEnv && showModelsError && (
        <p className="text-mmd text-accent-amber-foreground">
          {active.error?.message}
        </p>
      )}
    </div>
  );
}
