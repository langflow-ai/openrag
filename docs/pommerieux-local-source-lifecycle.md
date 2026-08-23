# Pommerieux local source lifecycle

## Scope and reference state

This document records the responsibility boundary of the
`agent/local-source-lifecycle` branch after integrating upstream OpenRAG.  It
is a maintenance and provenance branch, not a retrieval feature branch.

The comparison baseline is:

| State | Commit |
| --- | --- |
| Upstream `main` | `6d7678b73a08c9f6f0f0ba21cc724eba44dee69a` |
| FermedePommerieux `main` after the merge | `914fef893e20643e8c2c109c3faf54f765f390b1` |
| `agent/local-source-lifecycle` | `2957f2807e70d36f662afcda7e87f29edf80f5e2` |

`agent/local-source-lifecycle` is the base for future work that needs its
local-source guarantees.  In particular, it does **not** implement a new
retrieval engine, RRF, reranking, deep/exhaustive search, or a new chunking
strategy.  Those belong to a separate future branch.

## What upstream now provides

At the upstream reference commit, the common document-index contract already
contains `document_id`, `connector_file_id`, `source_url`, `connector_type`,
`filename`, `mimetype`, `page`, parser and chunking fields, source timestamps,
and ACL fields.  `DocumentIndexWriter` writes those fields and the OpenSearch
mapping supports them.

Upstream also provides the shared document-processing foundations:

- Docling conversion and its asynchronous polling path;
- Docling/index metadata such as page, parser, chunk size and overlap;
- multi-model KNN embeddings and dynamic embedding fields;
- a simple hybrid search that combines KNN and lexical `multi_match` clauses;
- metadata facets/filters and document ACL/DLS enforcement; and
- the current Langflow flows and OpenSearch component implementation.

`source_url` itself is therefore **not** a Pommerieux extension.  It is a
native upstream provenance field used by connectors and index/search results.

The current `flows/ingestion_flow.json` and `flows/openrag_agent.json` are
identical to the upstream reference.  Do not fork or regenerate either flow
without a concrete, reviewed integration need.

## What remains specific to Pommerieux

Pommerieux adds a lifecycle for an original file stored locally, using the
upstream `source_url` field to point to an authenticated local archive URL.
The extension provides:

- transactional local-source staging, commit, rollback, and discard;
- optional retention of the indexed original under a managed archive;
- deletion of ingestion-folder inputs only after successful indexing (or a
  confirmed unchanged content hash), while failed inputs remain available;
- cleanup of a retained archive once its final document reference is deleted;
- authenticated downloads and safe previews for supported local formats;
- DLS-backed visibility checks for download and preview;
- validation against path traversal and symlink escapes;
- persistent `archiving.enabled` configuration in YAML/DB/hybrid storage; and
- Settings, Knowledge, and chat UI for local-source archiving, download, and
  preview, including PDF reference-page navigation.

Local archive storage is intentionally unavailable in multi-user mode until a
separate tenant-isolation design is validated.  Remote HTTP(S) `source_url`
values remain supported without copying remote bytes.

## Upstream conflict surface

The lifecycle extension deliberately overlaps a small set of actively evolving
upstream areas.  Review these paths first when merging a future upstream:

| Area | Relevant paths | Why it overlaps |
| --- | --- | --- |
| Compose/runtime paths | `docker-compose.yml` | Archive, inbox, host-path, and public-URL environment variables |
| Settings navigation/UI | `frontend/app/settings/[tab]/page.tsx`, `frontend/app/settings/_components/settings-nav.tsx`, `frontend/app/settings/_components/archiving-settings-section.tsx` | Pommerieux adds the Archiving section alongside upstream Settings/Ingestion work |
| Knowledge/chat UI | `frontend/app/knowledge/*`, `frontend/app/chat/_components/*`, `frontend/components/source-preview-dialog.tsx`, `frontend/components/knowledge-actions-dropdown.tsx` | Source download and preview actions |
| Settings/config persistence | `src/config/config_manager.py`, `src/config/settings.py`, `src/db/migrations_runtime.py`, `src/db/models/workspace_config.py`, `src/db/repositories/workspace_config_repo.py`, `src/services/workspace_config_service.py` | Persisted archiving section and archive path defaults |
| Ingestion and deletion | `src/api/router.py`, `src/api/upload.py`, `src/api/documents.py`, `src/api/v1/documents.py`, `src/models/processors.py`, `src/services/task_service.py` | Archive transaction, consume-after-success, and archive cleanup |
| Local source API | `src/api/local_sources.py`, `src/services/local_source_service.py` | Pommerieux-only authenticated archive/download/preview service |

The common upstream paths `src/services/document_index_writer.py`,
`src/services/search_service.py`, `src/services/docling_service.py`,
`src/services/docling_polling_service.py`, `src/agent.py`, and both Langflow
flows are currently unchanged by lifecycle.  Keep them upstream-owned unless
future functionality demonstrably requires a small integration point.

## Validation status and known limitations

### Historical validation record

The branch handoff recorded the following earlier validation results:

- 193 focused lifecycle/API/archive/source-url/Docling/migration/status tests:
  PASS;
- 92 supplementary tests: PASS;
- five known pre-existing failures: one assertion expecting empty metadata even
  though the pipeline now supplies parser/Docling metadata, plus four tests
  with historical component/flow expectations;
- three collection errors shared with upstream/main;
- global Ruff count: 253 diagnostics before and after the merge, with no new
  lifecycle diagnostic reported;
- Node and Docker were unavailable in that validation environment.

Those aggregate counts are a handoff record, not a claim that this document
re-executed the same undocumented test selections.

### Recheck at `2957f280`

The current local recheck ran the lifecycle/archive selection plus
`tests/unit/test_processors_clear_stale_chunks.py`: **85 passed, 1 failed**.
The failure is
`test_connector_file_id_absent_when_not_provided`, whose assertion requires
`chunk.metadata == {}`.  The produced metadata now correctly includes
`parser`, `chunk_size`, and `chunk_overlap`; no production behavior was changed
to satisfy that obsolete assertion.

Running `uv run pytest tests/unit --maxfail=10 -q` stops at three collection
errors:

- `MCPServerURLUpdateError` is imported by
  `tests/unit/services/test_langflow_mcp_service.py` but is absent from
  `services.langflow_mcp_service`;
- `_extract_delta_text` is imported by `tests/unit/test_agent_response.py` but
  is absent from `agent`;
- `_extract_retrieval_sources` is imported by `tests/unit/test_agent_sources.py`
  but is absent from `agent`.

The corresponding symbols are also absent from the upstream reference source.
They are not lifecycle regressions.  Do not alter lifecycle production code to
make those historical tests importable.  If their intended upstream contract is
re-established, update the tests in a dedicated test-maintenance change.

## Technical debt

`src/config/paths.py:get_documents_path()` now delegates to
`config.settings.get_documents_path()`.  It remains a compatibility layer:
other `config.paths` helpers are still actively used, and `default_docs_service`
and `api.upload` still import this particular wrapper.  Do not remove it in a
cross-cutting cleanup.  It is a small future migration candidate once those
callers use `config.settings` directly.

## Handoff to retrieval v2

Retrieval v2 should reuse the upstream index/provenance contract and leave the
local archive service intact.  Its initial scope should add only the missing
retrieval responsibilities: deterministic lexical/vector fusion, result ranks
and debug traceability, optional reranking, document-level diversification,
and deep/exhaustive orchestration.

The existing hybrid query is not RRF and has no reranker, search rounds,
per-source diversification, or retrieval search identifier.  It does return
`source_url` and page, but a future retrieval contract should expose
`document_id` and `connector_file_id` explicitly as well.  The Langflow
OpenSearch component has its own search implementation, so a backend-only
change would not automatically affect agent retrieval; choose a minimal,
reviewed integration point before modifying either generated flow.
