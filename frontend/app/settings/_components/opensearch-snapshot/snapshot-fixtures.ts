/** Test fixtures for the snapshot import UI (response shapes per the route table). */
import type {
  PreflightResult,
  SnapshotDataset,
  SnapshotImport,
  SnapshotListing,
  SnapshotSource,
  SnapshotStatus,
} from "@/lib/opensearch-snapshot";
import { authPresets, withAuth } from "@/test-utils/fixtures/auth";

/** Admin who also holds the connector permissions the UI gates on. */
export const snapshotAdmin = withAuth(authPresets.admin, {
  usersMe: {
    permissions: [
      ...(authPresets.admin.usersMe?.permissions ?? []),
      "connectors:create",
      "connectors:delete:own",
    ],
  },
});

export function makeStatus(
  overrides: Partial<SnapshotStatus> = {},
): SnapshotStatus {
  return {
    enabled: true,
    reason: null,
    staging_type: "fs",
    security_managed: true,
    private_supported: true,
    ...overrides,
  };
}

export function makeSource(
  overrides: Partial<SnapshotSource> = {},
): SnapshotSource {
  return {
    id: "src-1",
    name: "Lab bucket",
    endpoint_url: null,
    region: "us-east-1",
    bucket: "snapshots",
    prefix: "scientists",
    path_style: true,
    verify_tls: true,
    has_credentials: true,
    created_at: "2026-11-19T10:00:00Z",
    updated_at: "2026-11-19T10:00:00Z",
    ...overrides,
  };
}

export function makeListing(): SnapshotListing {
  return {
    repository_generation: 3,
    snapshots: [
      {
        name: "scientists-v1",
        uuid: "uuid-1",
        state: "SUCCESS",
        version: "OpenSearch 3.8.0",
        indices: [
          { name: "famous_scientists", size_bytes: 2048 },
          { name: "scientific_discoveries", size_bytes: 5 * 1024 * 1024 },
          { name: ".kibana", size_bytes: 100 },
        ],
      },
      {
        name: "scientists-v2",
        uuid: "uuid-2",
        state: "SUCCESS",
        version: "OpenSearch 3.8.0",
        indices: [
          { name: "famous_scientists", size_bytes: 4096 },
          { name: "scientific_discoveries", size_bytes: 6 * 1024 * 1024 },
        ],
      },
    ],
  };
}

export function makePreflight(
  overrides: Partial<PreflightResult> = {},
): PreflightResult {
  return {
    ok: true,
    blockers: [],
    warnings: [],
    analyser_files: [],
    staged_bytes: 5 * 1024 * 1024,
    restored_bytes: 6 * 1024 * 1024,
    indices: [
      { name: "famous_scientists", created_version: "OpenSearch 3.8.0" },
    ],
    ...overrides,
  };
}

export function makeDataset(
  overrides: Partial<SnapshotDataset> = {},
): SnapshotDataset {
  return {
    id: "ds-1",
    ordinal: 0,
    source_index: "famous_scientists",
    index_alias: "ds_abcdefghij_0",
    display_name: "famous_scientists",
    description: "",
    doc_count: 12,
    field_map: { text_fields: ["bio"], title_field: "name", url_field: null },
    retrieval: { mode: "lexical" },
    fields: [
      { name: "name", type: "text" },
      { name: "bio", type: "text" },
      { name: "wiki_url", type: "keyword" },
    ],
    vector_fields: [],
    available_models: [],
    ...overrides,
  };
}

export function makeImport(
  overrides: Partial<SnapshotImport> = {},
): SnapshotImport {
  return {
    id: "imp-1",
    slug: "abcdefghij",
    name: "Scientists",
    source_id: "src-1",
    snapshot_name: "scientists-v1",
    snapshot_uuid: "uuid-1",
    written_by_version: "OpenSearch 3.8.0",
    source_indices: ["famous_scientists"],
    staged_bytes: 2048,
    status: "review",
    generation: 1,
    shared: false,
    is_owner: true,
    job: { state: "idle", kind: "import", error: null, task_id: null },
    role_json: null,
    created_at: "2026-11-19T10:00:00Z",
    updated_at: "2026-11-19T10:00:00Z",
    datasets: [makeDataset()],
    ...overrides,
  };
}
