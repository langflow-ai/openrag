export interface CatalogSelectOption {
  value: string;
  label: string;
  provider: string;
  default?: boolean;
  model?: CatalogModel;
}

/**
 * Structural subset of the LiteLLM catalogue payload. Kept local so this
 * helper stays importable from node:test without pulling react-query.
 */
export interface CatalogModel {
  model: string;
  mode?: string | null;
  capabilities?: string[];
  max_input_tokens?: number;
  max_output_tokens?: number;
  input_cost_per_token?: number;
  output_cost_per_token?: number;
  cache_read_input_token_cost?: number;
  deprecation_date?: string;
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
  name?: string;
  models?: CatalogModel[];
  embedding_models?: CatalogModel[];
  credential_fields?: CatalogCredentialField[];
}

interface ModelCatalogResponse {
  providers: CatalogProvider[];
}

export type SettingsCatalogProvider = string;

export type CatalogModelKind = "language" | "embedding" | "vision";

export interface CatalogOptionGroup {
  key: SettingsCatalogProvider;
  group: string;
  options: CatalogSelectOption[];
}

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
  return {
    value: entry.model,
    label: entry.model,
    provider,
    model: entry,
  };
}

/** Catalogue rows for one configured provider, mapped to ModelSelector options. */
export function groupedCatalogOptions(
  catalog: ModelCatalogResponse | undefined,
  configured: Partial<Record<string, boolean | undefined>> | undefined,
  kind: CatalogModelKind,
  options?: { includeEmpty?: boolean },
): CatalogOptionGroup[] {
  if (!catalog?.providers?.length) {
    return [];
  }
  const groups: CatalogOptionGroup[] = [];
  for (const provider of catalog.providers) {
    const key = provider.key;
    if (configured && !configured[key]) {
      continue;
    }
    const modelOptions = modelsForKind(provider, kind).map((entry) =>
      toOption(entry, key),
    );
    if (modelOptions.length === 0 && !options?.includeEmpty) {
      continue;
    }
    groups.push({
      key,
      group: provider.name || key,
      options: modelOptions,
    });
  }
  return groups;
}

/**
 * Onboarding lists every OpenRAG-credentialed provider, even before the
 * operator has saved a key — they are here to configure one.
 */
export function onboardingCatalogConfigured(
  _isEmbedding: boolean,
  _isCloudBrand: boolean,
): undefined {
  return undefined;
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
 * Credential controls for onboarding come directly from LiteLLM's provider
 * schema. The backend persists and encrypts arbitrary field keys.
 */
export function onboardingCredentialFields(
  catalog: ModelCatalogResponse | undefined,
  provider: SettingsCatalogProvider,
): CatalogCredentialField[] {
  return (
    catalog?.providers?.find((entry) => entry.key === provider)
      ?.credential_fields ?? [
      {
        key: "api_key",
        label: "API key",
        required: false,
        field_type: "password",
      },
      {
        key: "api_base",
        label: "API base",
        placeholder: "https://...",
        required: false,
        field_type: "text",
      },
    ]
  );
}
