export interface FilterInput {
  data_sources?: string[];
  document_types?: string[];
  owners?: string[];
  connector_types?: string[];
  /** Inclusive UTC bounds on indexed_time (ISO 8601). */
  created_after?: string;
  created_before?: string;
}

export interface NormalizedSelectedFilters {
  data_sources: string[];
  document_types: string[];
  owners: string[];
  connector_types: string[];
}

function normalizeFilterDimension(values?: string[]): string[] {
  if (!values || values.includes("*")) {
    return [];
  }
  return values;
}

function normalizeSelectedFilters(
  filters?: FilterInput,
): NormalizedSelectedFilters {
  return {
    data_sources: normalizeFilterDimension(filters?.data_sources),
    document_types: normalizeFilterDimension(filters?.document_types),
    owners: normalizeFilterDimension(filters?.owners),
    connector_types: normalizeFilterDimension(filters?.connector_types),
  };
}

function dateBound(value?: string): string | undefined {
  return typeof value === "string" && value !== "" ? value : undefined;
}

/**
 * Build the `filters` object for search/chat/nudge requests.
 *
 * Saved date bounds are included by default. The Knowledge page passes
 * `includeDates: false` because it sends its effective bounds separately, so a
 * cleared temporary range can never fall back to the saved one.
 */
export function buildSearchPayloadFilters(
  filters?: FilterInput,
  options: { includeDates?: boolean } = {},
): FilterInput | undefined {
  const { includeDates = true } = options;
  const normalized = normalizeSelectedFilters(filters);
  const payloadFilters: FilterInput = {};

  if (normalized.data_sources.length > 0) {
    payloadFilters.data_sources = normalized.data_sources;
  }
  if (normalized.document_types.length > 0) {
    payloadFilters.document_types = normalized.document_types;
  }
  if (normalized.owners.length > 0) {
    payloadFilters.owners = normalized.owners;
  }
  if (normalized.connector_types.length > 0) {
    payloadFilters.connector_types = normalized.connector_types;
  }
  if (includeDates) {
    const createdAfter = dateBound(filters?.created_after);
    const createdBefore = dateBound(filters?.created_before);
    if (createdAfter) payloadFilters.created_after = createdAfter;
    if (createdBefore) payloadFilters.created_before = createdBefore;
  }

  return Object.keys(payloadFilters).length > 0 ? payloadFilters : undefined;
}
