export interface FilterInput {
  data_sources?: string[];
  document_types?: string[];
  owners?: string[];
  connector_types?: string[];
  /** Inclusive UTC bounds on indexed_time (ISO 8601). */
  created_after?: string;
  created_before?: string;
  document_ids?: string[];
  web_source_ids?: string[];
}

export interface NormalizedSelectedFilters {
  data_sources: string[];
  document_types: string[];
  owners: string[];
  connector_types: string[];
  document_ids: string[];
  web_source_ids: string[];
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
    document_ids: normalizeFilterDimension(filters?.document_ids),
    web_source_ids: normalizeFilterDimension(filters?.web_source_ids),
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
  if (normalized.document_ids.length > 0) {
    payloadFilters.document_ids = normalized.document_ids;
  }
  if (normalized.web_source_ids.length > 0) {
    payloadFilters.web_source_ids = normalized.web_source_ids;
  }

  return Object.keys(payloadFilters).length > 0 ? payloadFilters : undefined;
}

/**
 * Whether a filter narrows chat retrieval. Chat only applies sources, types,
 * owners, connectors and dates; the saved search query affects the Knowledge
 * table alone.
 */
export function filterRestrictsChat(filters?: FilterInput): boolean {
  return buildSearchPayloadFilters(filters) !== undefined;
}

/** `filterRestrictsChat` for a saved filter's raw `query_data` string. */
export function queryDataRestrictsChat(queryData?: string | null): boolean {
  if (!queryData) return false;
  try {
    const parsed = JSON.parse(queryData) as { filters?: FilterInput };
    return filterRestrictsChat(parsed?.filters);
  } catch {
    return false;
  }
}

/**
 * Mimetypes named by a query that is a bare file extension (`.txt`, `*.pdf`,
 * `PDF`). Returns an empty list for any other query.
 */
export function extensionMimetypes(
  query: string,
  fileTypes: Record<string, string[]>,
): string[] {
  const match = query.trim().match(/^\*?\.?([a-z0-9]+)$/i);
  if (!match) return [];
  const extension = `.${match[1].toLowerCase()}`;
  return Object.entries(fileTypes)
    .filter(([, extensions]) => extensions.includes(extension))
    .map(([mimetype]) => mimetype);
}
