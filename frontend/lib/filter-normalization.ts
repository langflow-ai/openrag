export interface FilterInput {
  data_sources?: string[];
  document_types?: string[];
  owners?: string[];
  connector_types?: string[];
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

export function buildSearchPayloadFilters(
  filters?: FilterInput,
): FilterInput | undefined {
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
  if (normalized.document_ids.length > 0) {
    payloadFilters.document_ids = normalized.document_ids;
  }
  if (normalized.web_source_ids.length > 0) {
    payloadFilters.web_source_ids = normalized.web_source_ids;
  }

  return Object.keys(payloadFilters).length > 0 ? payloadFilters : undefined;
}
