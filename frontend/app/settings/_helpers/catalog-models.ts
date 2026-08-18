export interface CatalogSelectOption {
  value: string;
  label: string;
  provider: string;
  default?: boolean;
}

/**
 * Structural subset of the LiteLLM catalogue payload. Kept local so this
 * helper stays importable from node:test without pulling react-query.
 */
interface CatalogModel {
  model: string;
  capabilities?: string[];
}

export interface CatalogCredentialField {
  key: string;
  label: string;
  placeholder?: string | null;
  tooltip?: string | null;
  required: boolean;
  field_type: string;
  options?: unknown;
  default_value?: unknown;
}

interface CatalogProvider {
  key: string;
  models?: CatalogModel[];
  embedding_models?: CatalogModel[];
  credential_fields?: CatalogCredentialField[];
}

interface ModelCatalogResponse {
  providers: CatalogProvider[];
}

/** Providers OpenRAG can credential; LiteLLM lists many more. */
export type SettingsCatalogProvider =
  | "openai"
  | "anthropic"
  | "ollama"
  | "watsonx";

export type CatalogModelKind = "language" | "embedding" | "vision";

export interface CatalogOptionGroup {
  key: SettingsCatalogProvider;
  group: string;
  options: CatalogSelectOption[];
}

/**
 * Providers OpenRAG can actually call. The LiteLLM catalogue lists ~140
 * vendors; the gateway only has credentials for these four.
 */
const SETTINGS_CATALOG_GROUPS: {
  key: SettingsCatalogProvider;
  group: string;
}[] = [
  { key: "openai", group: "OpenAI" },
  { key: "anthropic", group: "Anthropic" },
  { key: "ollama", group: "Ollama" },
  { key: "watsonx", group: "IBM watsonx.ai" },
];

/** Credential keys the onboarding API can actually persist today. */
const ONBOARDING_FIELD_KEYS: Record<SettingsCatalogProvider, string[]> = {
  openai: ["api_key"],
  anthropic: ["api_key"],
  ollama: ["api_base"],
  watsonx: ["api_base", "project_id", "api_key"],
};

const ONBOARDING_REQUIRED_FIELDS: Record<
  SettingsCatalogProvider,
  Record<string, boolean>
> = {
  openai: { api_key: true },
  anthropic: { api_key: true },
  ollama: { api_base: true },
  watsonx: { api_base: true, api_key: true, project_id: true },
};

const FALLBACK_ONBOARDING_FIELDS: Record<
  SettingsCatalogProvider,
  CatalogCredentialField[]
> = {
  openai: [
    {
      key: "api_key",
      label: "OpenAI API Key",
      placeholder: "sk-...",
      tooltip: "The API key for your OpenAI account.",
      required: true,
      field_type: "password",
    },
  ],
  anthropic: [
    {
      key: "api_key",
      label: "Anthropic API Key",
      placeholder: "sk-...",
      tooltip: "The API key for your Anthropic account.",
      required: true,
      field_type: "password",
    },
  ],
  ollama: [
    {
      key: "api_base",
      label: "Ollama Base URL",
      placeholder: "http://localhost:11434",
      tooltip: "Base URL of your Ollama server",
      required: true,
      field_type: "text",
      default_value: "http://localhost:11434",
    },
  ],
  watsonx: [
    {
      key: "api_base",
      label: "watsonx.ai API Endpoint",
      placeholder: "https://us-south.ml.cloud.ibm.com",
      tooltip: "Base URL of the API",
      required: true,
      field_type: "text",
      default_value: "https://us-south.ml.cloud.ibm.com",
    },
    {
      key: "project_id",
      label: "watsonx Project ID",
      placeholder: "your-project-id",
      tooltip: "Project ID for the model",
      required: true,
      field_type: "text",
    },
    {
      key: "api_key",
      label: "watsonx API Key",
      placeholder: "your-api-key",
      tooltip: "API key to access watsonx.ai",
      required: true,
      field_type: "password",
    },
  ],
};

function modelsForKind(
  provider: CatalogProvider,
  kind: CatalogModelKind,
): CatalogModel[] {
  if (kind === "embedding") {
    return provider.embedding_models ?? [];
  }
  const chat = provider.models ?? [];
  if (kind === "vision") {
    return chat.filter((entry) => entry.capabilities?.includes("vision"));
  }
  return chat;
}

function toOption(entry: CatalogModel, provider: string): CatalogSelectOption {
  return { value: entry.model, label: entry.model, provider };
}

/** Catalogue rows for one configured provider, mapped to ModelSelector options. */
export function groupedCatalogOptions(
  catalog: ModelCatalogResponse | undefined,
  configured: Partial<Record<SettingsCatalogProvider, boolean | undefined>>,
  kind: CatalogModelKind,
  options?: { includeEmpty?: boolean },
): CatalogOptionGroup[] {
  if (!catalog?.providers?.length) {
    return [];
  }
  const byKey = new Map(
    catalog.providers.map((provider) => [provider.key, provider]),
  );
  const groups: CatalogOptionGroup[] = [];
  for (const { key, group } of SETTINGS_CATALOG_GROUPS) {
    if (!configured[key]) {
      continue;
    }
    const provider = byKey.get(key);
    const modelOptions = provider
      ? modelsForKind(provider, kind).map((entry) => toOption(entry, key))
      : [];
    if (modelOptions.length === 0 && !options?.includeEmpty) {
      continue;
    }
    groups.push({ key, group, options: modelOptions });
  }
  return groups;
}

/**
 * Onboarding lists every OpenRAG-credentialed provider, even before the
 * operator has saved a key — they are here to configure one.
 */
export function onboardingCatalogConfigured(
  isEmbedding: boolean,
  isCloudBrand: boolean,
): Partial<Record<SettingsCatalogProvider, boolean>> {
  return {
    openai: true,
    anthropic: !isEmbedding,
    watsonx: true,
    ollama: !isCloudBrand,
  };
}

/** Append live /models/{provider} rows that the catalogue does not already list. */
export function mergeLiveCatalogOptions(
  groups: CatalogOptionGroup[],
  provider: string | undefined,
  live: CatalogSelectOption[],
): CatalogOptionGroup[] {
  if (!provider || live.length === 0) {
    return groups;
  }
  return groups.map((group) => {
    if (group.key !== provider) {
      return group;
    }
    const seen = new Set(group.options.map((option) => option.value));
    const extra = live.filter((option) => !seen.has(option.value));
    if (extra.length === 0) {
      return group;
    }
    return { ...group, options: [...group.options, ...extra] };
  });
}

/**
 * Credential controls for onboarding: LiteLLM's field spec, clipped to the
 * keys classic OpenRAG can actually store.
 */
export function onboardingCredentialFields(
  catalog: ModelCatalogResponse | undefined,
  provider: SettingsCatalogProvider,
): CatalogCredentialField[] {
  const keep = new Set(ONBOARDING_FIELD_KEYS[provider]);
  const requiredOverride = ONBOARDING_REQUIRED_FIELDS[provider];
  const raw =
    catalog?.providers?.find((entry) => entry.key === provider)
      ?.credential_fields ?? [];
  const filtered = raw
    .filter((field) => keep.has(field.key))
    .map((field) => ({
      ...field,
      required: requiredOverride[field.key] ?? field.required,
    }));
  const fallback = FALLBACK_ONBOARDING_FIELDS[provider] ?? [];
  return ONBOARDING_FIELD_KEYS[provider].flatMap((key) => {
    const fromCatalog = filtered.find((field) => field.key === key);
    const fromFallback = fallback.find((field) => field.key === key);
    const field = fromCatalog ?? fromFallback;
    return field ? [field] : [];
  });
}
