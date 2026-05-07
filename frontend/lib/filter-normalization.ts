/** One selected source: stable id when available, plus filename for legacy OS queries. */
export interface DataSourceRef {
  filename?: string;
  document_id?: string | null;
}

export interface FilterInput {
  data_sources?: string[];
  /** When set, search matches by document_id and/or filename (rename-safe). */
  data_source_refs?: DataSourceRef[];
  document_types?: string[];
  owners?: string[];
  connector_types?: string[];
}

export interface NormalizedSelectedFilters {
  data_sources: string[];
  data_source_refs: DataSourceRef[];
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

function normalizeDataSourceRefs(filters?: FilterInput): DataSourceRef[] {
  const refs = filters?.data_source_refs;
  if (!refs?.length) {
    return [];
  }
  // Refs are authoritative for the source dimension; do not drop them when
  // data_sources is missing or wildcard (saved filters often use ["*"] + refs).
  return refs.filter(
    (r) =>
      r &&
      ((typeof r.filename === "string" && r.filename.trim().length > 0) ||
        (typeof r.document_id === "string" && r.document_id.trim().length > 0)),
  );
}

export function normalizeSelectedFilters(
  filters?: FilterInput,
): NormalizedSelectedFilters {
  const data_sources = normalizeFilterDimension(filters?.data_sources);
  return {
    data_sources,
    data_source_refs: normalizeDataSourceRefs(filters),
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

  if (normalized.data_source_refs.length > 0) {
    payloadFilters.data_sources =
      filters?.data_sources?.filter((v) => v !== "*") ?? [];
    payloadFilters.data_source_refs = normalized.data_source_refs;
  } else if (normalized.data_sources.length > 0) {
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
