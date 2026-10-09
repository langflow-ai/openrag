import { useMemo } from "react";
import { useDiscoverProviderModelsQuery } from "@/app/api/queries/useDiscoverProviderModelsQuery";
import {
  type CatalogCredentialField,
  type CatalogSelectOption,
  providerCatalogOptions,
  providerDiscoversModels,
  withDiscoveredModels,
} from "@/components/models/catalog-models";
import { useDebouncedValue } from "@/lib/debounce";

type Catalog = Parameters<typeof providerCatalogOptions>[0];

export interface OnboardingModelDiscovery {
  /** Whether the provider can list its own models from unsaved credentials. */
  discovers: boolean;
  /** Picker options: what the cluster serves, or the catalogue's rows. */
  models: CatalogSelectOption[];
  /** One line on where `models` came from, or null when there is nothing to say. */
  status: string | null;
  /**
   * No answer yet for the credentials as typed. A changed credential starts a
   * new query with no data, so `models` briefly falls back to the catalogue.
   */
  inFlight: boolean;
}

/**
 * The model picker's options for an onboarding provider, asking the cluster
 * what it serves when the provider can say.
 *
 * A cluster-hosted provider serves whatever its operator deployed, and the
 * catalogue can only list it once credentials are saved. This asks the cluster
 * with what has been typed so far, so the picker offers what it serves rather
 * than the configured fallback. Any other provider gets the catalogue's rows.
 */
export function useOnboardingModelDiscovery({
  catalog,
  provider,
  isEmbedding,
  fields,
  credentials,
  activeKeys,
  savedSecrets,
  authMethod,
}: {
  catalog: Catalog;
  provider: string;
  isEmbedding: boolean;
  fields: CatalogCredentialField[];
  credentials: Record<string, string>;
  /** The keys the chosen auth method uses, or null when every field applies. */
  activeKeys: Set<string> | null;
  savedSecrets: Set<string>;
  authMethod?: string;
}): OnboardingModelDiscovery {
  const discovers = providerDiscoversModels(catalog, provider);
  const typedCredentials: Record<string, string> = {};
  for (const [key, value] of Object.entries(credentials)) {
    const trimmed = (value ?? "").trim();
    if (trimmed && (!activeKeys || activeKeys.has(key)))
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
    (field) => !activeKeys || activeKeys.has(field.key),
  );
  const ready =
    discovers &&
    activeFields.every((field) => !field.required || hasValue(field.key)) &&
    activeFields
      .filter((field) => field.field_type === "password")
      .every((field) => hasValue(field.key));
  const discovery = useDiscoverProviderModelsQuery(
    { provider, credentials: discoveryCredentials, authMethod },
    { enabled: ready },
  );
  const discovered = ready ? discovery.data : undefined;
  const discoveredHalf = isEmbedding
    ? discovered?.embedding_models
    : discovered?.models;
  const inFlight = ready && (discovery.isPending || discovery.isFetching);

  const models = useMemo(
    () =>
      providerCatalogOptions(
        withDiscoveredModels(catalog, provider, discovered),
        provider,
        isEmbedding ? "embedding" : "language",
      ),
    [catalog, provider, isEmbedding, discovered],
  );

  const kindLabel = isEmbedding ? "embedding" : "language";
  // A provider that discovers its models may configure no fallback at all, so
  // an empty picker means "not asked yet" or "could not ask", never "this
  // provider has nothing to offer".
  let status: string | null = null;
  if (discovers && !ready) {
    if (models.length === 0) {
      status = `Enter the credentials above to list the ${kindLabel} models the cluster serves.`;
    }
  } else if (ready) {
    if (inFlight) {
      status = "Checking which models the cluster serves…";
    } else if (discovery.isError || !discoveredHalf) {
      status =
        models.length > 0
          ? `Couldn't list ${kindLabel} models from the cluster — showing configured defaults. Type a model ID to use another.`
          : `Couldn't list ${kindLabel} models from the cluster. Type a model ID to continue.`;
    } else if (discoveredHalf.length > 0) {
      status = `Showing ${discoveredHalf.length} ${kindLabel} ${
        discoveredHalf.length === 1 ? "model" : "models"
      } served by the cluster.`;
    } else {
      status = `The cluster lists no ${kindLabel} models. Type a model ID to continue.`;
    }
  }

  return { discovers, models, status, inFlight };
}
