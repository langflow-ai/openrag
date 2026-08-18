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

interface CatalogProvider {
  key: string;
  models?: CatalogModel[];
  embedding_models?: CatalogModel[];
}

interface ModelCatalogResponse {
  providers: CatalogProvider[];
}

/** Providers OpenRAG can credential; LiteLLM lists many more. */
type SettingsCatalogProvider = "openai" | "anthropic" | "ollama" | "watsonx";

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

type CatalogModelKind = "language" | "embedding" | "vision";

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
): {
  key: SettingsCatalogProvider;
  group: string;
  options: CatalogSelectOption[];
}[] {
  if (!catalog?.providers?.length) {
    return [];
  }
  const byKey = new Map(
    catalog.providers.map((provider) => [provider.key, provider]),
  );
  const groups: {
    key: SettingsCatalogProvider;
    group: string;
    options: CatalogSelectOption[];
  }[] = [];
  for (const { key, group } of SETTINGS_CATALOG_GROUPS) {
    if (!configured[key]) {
      continue;
    }
    const provider = byKey.get(key);
    if (!provider) {
      continue;
    }
    const options = modelsForKind(provider, kind).map((entry) =>
      toOption(entry, key),
    );
    if (options.length === 0) {
      continue;
    }
    groups.push({ key, group, options });
  }
  return groups;
}
