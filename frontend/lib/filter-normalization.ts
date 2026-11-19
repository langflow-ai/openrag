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
  /**
   * Imported snapshot datasets to search alongside documents. Unlike the other
   * dimensions: missing or `["*"]` = every visible dataset, `[]` = none.
   */
  datasets?: string[];
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

/**
 * Parse a saved/typed dataset selection.
 * `undefined` = all visible datasets (missing, malformed or `["*"]`),
 * `[]` = none, otherwise exactly the listed ids.
 */
export function normalizeDatasetSelection(
  values: unknown,
): string[] | undefined {
  if (!Array.isArray(values) || values.includes("*")) return undefined;
  return values.filter((value): value is string => typeof value === "string");
}

/**
 * Apply one checkbox change to a selection. Ticking the last unticked dataset
 * returns to `undefined` (all) so datasets imported later are included too;
 * ids no longer visible stay in an explicit list untouched.
 */
export function toggleDatasetSelection(
  selection: string[] | undefined,
  visibleIds: string[],
  id: string,
  checked: boolean,
): string[] | undefined {
  const current =
    selection === undefined || selection.includes("*") ? visibleIds : selection;
  const next = checked
    ? current.includes(id)
      ? [...current]
      : [...current, id]
    : current.filter((value) => value !== id);
  return visibleIds.every((value) => next.includes(value)) ? undefined : next;
}

export function isDatasetSelected(
  selection: string[] | undefined,
  id: string,
): boolean {
  return (
    selection === undefined || selection.includes("*") || selection.includes(id)
  );
}

function dateBound(value?: string): string | undefined {
  return typeof value === "string" && value !== "" ? value : undefined;
}

/**
 * Build the `filters` object for search/chat/nudge requests.
 *
 * Saved date bounds are included by default. The Knowledge page passes
 * `includeDates: false` because it sends its effective bounds separately, so a
 * cleared temporary range can never fall back to the saved one. Callers that
 * only search documents (Knowledge page, suggestions) pass
 * `includeDatasets: false`.
 */
export function buildSearchPayloadFilters(
  filters?: FilterInput,
  options: { includeDates?: boolean; includeDatasets?: boolean } = {},
): FilterInput | undefined {
  const { includeDates = true, includeDatasets = true } = options;
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
  if (includeDatasets) {
    // `[]` is meaningful (search no datasets), so it is kept.
    const datasets = normalizeDatasetSelection(filters?.datasets);
    if (datasets !== undefined) payloadFilters.datasets = datasets;
  }

  return Object.keys(payloadFilters).length > 0 ? payloadFilters : undefined;
}
