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

/** Models onboarding actually validates (chat + tools / a real embedding). */
const PREFERRED_LANGUAGE_MODELS = [
  "gpt-4o-mini",
  "gpt-4o",
  "gpt-4.1-mini",
  "gpt-4.1",
  "claude-sonnet-4-6",
  "claude-sonnet-4-5",
];
const PREFERRED_EMBEDDING_MODELS = [
  "text-embedding-3-small",
  "text-embedding-3-large",
];

/** A YYYY-MM-DD or YYYYMMDD snapshot stamp inside a model id. */
const SNAPSHOT_DATE = /(20\d{2})-?(\d{2})-?(\d{2})(?!\d)/;

/**
 * How recent a model id looks, most-recent-first. Nothing in LiteLLM's data
 * says when a model shipped — `deprecation_date` is the only date it carries,
 * and it is not a stand-in: Anthropic retires on a rolling year so it tracks
 * release almost exactly, but OpenAI sunsets a decade of models on one shared
 * date, which would rank gpt-3.5-turbo above gpt-5. So recency is read off the
 * id itself.
 *
 * Version before snapshot, deliberately. `gpt-5` and `gpt-5-2025-08-07` are
 * the same model, and the bare alias is the one to offer — so an id with no
 * stamp sorts *above* its dated snapshots rather than below them.
 *
 * Providers that number by size rather than version (watsonx's `jais-13b`,
 * `granite-3-8b`) get an ordering that means nothing in particular. It is
 * stable and alphabetical within a version, which is all it needs to be.
 */
function recencyRank(name: string): Array<number> {
  const stamp = SNAPSHOT_DATE.exec(name);
  // Strip the stamp before reading version digits, or 2025 becomes a version.
  const withoutStamp = stamp ? name.replace(stamp[0], "") : name;
  const version = (withoutStamp.match(/\d+(?:\.\d+)?/g) ?? [])
    .slice(0, 3)
    .map(Number);
  while (version.length < 3) version.push(-1);

  const stampRank = stamp
    ? -Number(`${stamp[1]}${stamp[2]}${stamp[3]}`)
    : -Number.MAX_SAFE_INTEGER;

  return [-version[0], -version[1], -version[2], stampRank];
}

function optionRank(
  option: CatalogSelectOption,
  kind: CatalogModelKind,
): Array<number | string> {
  const name = option.value;
  const caps = option.model?.capabilities ?? [];
  const preferred =
    kind === "embedding"
      ? PREFERRED_EMBEDDING_MODELS
      : PREFERRED_LANGUAGE_MODELS;
  const preferredIndex = preferred.indexOf(name);
  return [
    // The catalogue no longer carries LiteLLM's `ft:` pricing templates, but a
    // live `/models/openai` fetch returns the operator's real fine-tunes. Those
    // are callable and stay listed — just never above a base model.
    name.toLowerCase().startsWith("ft:") ? 1 : 0,
    caps.length === 0 ? 1 : 0,
    kind === "language" && !caps.includes("function_calling") ? 1 : 0,
    kind === "vision" && !caps.includes("vision") ? 1 : 0,
    ...recencyRank(name),
    // Only reached by ids that look equally recent: the embedding lists are
    // undated and unversioned, so this is what still puts a validated default
    // on top there.
    preferredIndex === -1 ? preferred.length : preferredIndex,
    name,
  ];
}

function compareCatalogOptions(
  left: CatalogSelectOption,
  right: CatalogSelectOption,
  kind: CatalogModelKind,
): number {
  const leftRank = optionRank(left, kind);
  const rightRank = optionRank(right, kind);
  for (let index = 0; index < leftRank.length; index += 1) {
    if (leftRank[index] < rightRank[index]) return -1;
    if (leftRank[index] > rightRank[index]) return 1;
  }
  return 0;
}

function groupProviderKey(group: {
  key?: string;
  provider?: string;
}): string | undefined {
  return group.provider ?? group.key;
}

/**
 * Resolve a picker row by provider + model. The same LiteLLM model id can
 * appear under many vendors; name-only lookup always returns the first one.
 */
export function findGroupedSelection<
  G extends {
    key?: string;
    provider?: string;
    options: Array<{
      value: string;
      provider?: string;
      model?: CatalogModel;
    }>;
  },
>(
  groups: G[],
  model: string | undefined,
  provider?: string,
): { group: G; option: G["options"][number] | undefined } | undefined {
  if (provider) {
    const group = groups.find((entry) => groupProviderKey(entry) === provider);
    if (!group) {
      return undefined;
    }
    return {
      group,
      option: model
        ? group.options.find((option) => option.value === model)
        : undefined,
    };
  }
  if (!model) {
    return undefined;
  }
  const group = groups.find((entry) =>
    entry.options.some((option) => option.value === model),
  );
  if (!group) {
    return undefined;
  }
  return {
    group,
    option: group.options.find((option) => option.value === model),
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
    const modelOptions = modelsForKind(provider, kind)
      .map((entry) => toOption(entry, key))
      .sort((left, right) => compareCatalogOptions(left, right, kind));
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

/**
 * Append live `/models/{provider}` rows that the catalogue does not list.
 *
 * Some providers' inventory is only knowable from the running server: watsonx
 * publishes *no* embedding models in LiteLLM's bundled table at all, and
 * Ollama serves whatever the operator pulled. Without this the watsonx group
 * is empty for embeddings, and `groupedCatalogOptions` then drops the group
 * entirely — which is why watsonx was missing from the embedding picker
 * rather than merely short of options. So the merge creates the group when
 * the catalogue produced none.
 */
export function mergeLiveCatalogOptions(
  groups: CatalogOptionGroup[],
  provider: string | undefined,
  live: CatalogSelectOption[],
  displayName?: string,
): CatalogOptionGroup[] {
  if (!provider || live.length === 0) {
    return groups;
  }
  if (!groups.some((group) => group.key === provider)) {
    return [
      ...groups,
      { key: provider, group: displayName || provider, options: live },
    ];
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
 * Providers whose model list comes from the running server, not from
 * LiteLLM's bundled table. watsonx publishes no embedding models in that
 * table at all, and Ollama serves whatever the operator pulled locally.
 */
export const LIVE_INVENTORY_PROVIDERS = new Set(["watsonx", "ollama"]);

/** A live `/models/{provider}` row as a picker option. */
export function liveModelOption(
  model: string,
  provider: string,
): CatalogSelectOption {
  return { value: model, label: model, provider };
}

/**
 * Credential controls for onboarding come directly from LiteLLM's provider
 * schema. The backend persists and encrypts arbitrary field keys.
 */
export interface SavedProviderSnapshot {
  configured?: boolean;
  has_api_key?: boolean;
  endpoint?: string;
  project_id?: string;
  credential_values?: Record<string, string>;
  secret_fields?: string[];
}

export interface SavedProvidersSnapshot {
  openai?: SavedProviderSnapshot;
  anthropic?: SavedProviderSnapshot;
  watsonx?: SavedProviderSnapshot;
  ollama?: SavedProviderSnapshot;
  custom?: Record<string, SavedProviderSnapshot>;
}

/** Secrets already stored for this vendor — including the four legacy slots. */
export function savedSecretFieldsForProvider(
  providers: SavedProvidersSnapshot | undefined,
  provider: string,
): string[] {
  if (!providers || !provider) {
    return [];
  }
  const fields = new Set(providers.custom?.[provider]?.secret_fields ?? []);
  if (provider === "openai" && providers.openai?.has_api_key) {
    fields.add("api_key");
  }
  if (provider === "anthropic" && providers.anthropic?.has_api_key) {
    fields.add("api_key");
  }
  if (provider === "watsonx" && providers.watsonx?.has_api_key) {
    fields.add("api_key");
  }
  return [...fields];
}

export function savedCredentialValuesForProvider(
  providers: SavedProvidersSnapshot | undefined,
  provider: string,
): Record<string, string> {
  const values = {
    ...(providers?.custom?.[provider]?.credential_values ?? {}),
  };
  if (provider === "watsonx") {
    if (providers?.watsonx?.endpoint) {
      values.api_base ??= providers.watsonx.endpoint;
    }
    if (providers?.watsonx?.project_id) {
      values.project_id ??= providers.watsonx.project_id;
    }
  }
  if (provider === "ollama" && providers?.ollama?.endpoint) {
    values.api_base ??= providers.ollama.endpoint;
  }
  return values;
}

/** True when onboarding can reuse credentials already saved for this vendor. */
export function providerCredentialsSatisfied(
  providers: SavedProvidersSnapshot | undefined,
  provider: string,
  catalog: ModelCatalogResponse | undefined,
): boolean {
  if (!providers || !provider) {
    return false;
  }
  const required = onboardingCredentialFields(catalog, provider).filter(
    (field) => field.required,
  );
  const secrets = new Set(savedSecretFieldsForProvider(providers, provider));
  const values = savedCredentialValuesForProvider(providers, provider);
  if (required.length === 0) {
    return Boolean(
      secrets.size > 0 ||
        Object.keys(values).length > 0 ||
        providers.custom?.[provider]?.configured ||
        (provider === "openai" && providers.openai?.configured) ||
        (provider === "anthropic" && providers.anthropic?.configured) ||
        (provider === "watsonx" && providers.watsonx?.configured) ||
        (provider === "ollama" && providers.ollama?.configured),
    );
  }
  return required.every(
    (field) => Boolean(values[field.key]?.trim()) || secrets.has(field.key),
  );
}

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
