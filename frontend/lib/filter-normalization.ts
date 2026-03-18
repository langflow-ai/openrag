export interface FilterInput {
  data_sources?: string[];
  document_types?: string[];
  owners?: string[];
  connector_types?: string[];
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

export function normalizeSelectedFilters(
  filters?: FilterInput,
): NormalizedSelectedFilters {
  return {
    data_sources: normalizeFilterDimension(filters?.data_sources),
    document_types: normalizeFilterDimension(filters?.document_types),
    owners: normalizeFilterDimension(filters?.owners),
    connector_types: normalizeFilterDimension(filters?.connector_types),
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

  return Object.keys(payloadFilters).length > 0 ? payloadFilters : undefined;
}
