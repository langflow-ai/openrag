# URL Connector Feature Plan

Status: approved product direction; implementation not started  
Scope: OSS and IBM-branded OpenRAG  
Ingestion pipeline: OpenRAG native ingestion only (Langflow-less)

## 1. Objective

Add a managed URL connector that crawls public websites and represents them in Knowledge as a parent URL source containing individually indexed child pages.

The connector must:

- Appear as connected in Settings, with an **Add Knowledge** action.
- Appear as **URL** in the Add Knowledge dropdown.
- Open an ingestion modal instead of navigating to a separate upload page.
- Always use OpenRAG's native ingestion pipeline, even when Langflow ingestion is enabled globally.
- Reuse the Knowledge page's table, search, pagination, row actions, loading states, and OSS/IBM design behavior.
- Crawl only approved public destinations and enforce non-disableable safety limits.
- Avoid ingesting the same canonical URL or unchanged content repeatedly.

## 2. Confirmed product decisions

### 2.1 Parent and child hierarchy

- Each URL connection creates one parent item on the main Knowledge page.
- Clicking the parent row opens its child-page view.
- Every unique crawled page is stored and indexed as a separate child document.
- Every child retains a stable relationship to its parent through `web_source_id`.
- Clicking a child opens the existing Chunks experience for that child document.
- Child pages do not appear as independent top-level Knowledge rows.
- Top-level Knowledge search may match child content, but displays the matching parent source rather than leaking children into the root table.

### 2.2 Parent presentation

- Use the existing URL icon already used for URL files in the Knowledge table.
- Preserve the same icon size, color, and row styling as other Knowledge items.
- Add a small badge at the icon's bottom-right showing the total number of child items, including disabled children.
- Show only the connection name in the row.
- Show the root URL in the title tooltip; do not add a second URL line.
- Clicking either the active title area or URL icon opens the child-page view.

### 2.3 Sync and delete availability

Parent-level **Sync** and **Delete** must be available in both places:

1. The parent row's overflow menu on the main Knowledge page.
2. The child-page view's source-level actions.

Parent actions:

- **Sync** follows the source's saved re-sync behavior.
- **Delete** removes the source, every child record, and all indexed chunks belonging to those children.
- Parent deletion requires a destructive confirmation that states how many child pages will be removed.

Child actions, available from the child's text-only overflow menu:

- **View chunks**
- **Re-sync page**
- **Delete page**

Deleting a child is reversible suppression:

- The child remains visible in the child table with a **Disabled** status.
- Its indexed chunks are deleted immediately.
- Root-level sync skips that child even when the URL is rediscovered.
- The child remains disabled across scheduled sync, manual root sync, and Sync All.
- **Re-sync page** explicitly clears the suppression, fetches the page, and re-ingests it.
- If a suppressed page must be fetched to discover other in-scope links—especially when it is the seed page—the crawler may traverse it, but must not index its content until explicitly re-enabled.

### 2.4 Root sync behavior

Root sync always reuses the saved crawl and safety settings.

- **Full crawl; ingest returned pages**: repeat the saved crawl scope, ingest new or changed non-disabled pages, and reconcile missing pages after a complete successful crawl.
- **Ingest only root page**: update only the canonical starting page and leave existing children unchanged.
- In both modes, manually disabled children are skipped.
- Sync All invokes the same source-level sync behavior for every URL source.

### 2.5 Removed pages

- **Retain in corpus**: a page missing from a complete crawl remains indexed and is marked unavailable/retained.
- **Delete**: a page missing from a complete crawl has its indexed chunks removed.
- Incomplete, failed, timed-out, or safety-capped crawls never delete missing pages.
- Manual suppression is distinct from remote removal and is never reversed by reconciliation.

## 3. Add URL modal

### 3.1 Entry points

The same modal opens from:

- Add Knowledge → URL.
- Settings → URL → Add Knowledge.
- A supported deep link such as `/knowledge?add=url`.

The previous `/upload/url` route, if retained for compatibility, redirects to `/knowledge?add=url`.

The modal never lists previously ingested websites. Existing sources live only on the Knowledge page.

### 3.2 Visual and interaction reference

The supplied screenshots define the information architecture:

- Large two-step modal.
- Persistent title: **Add a Website connection**.
- Subtitle: **Crawl public website content into OpenRAG.**
- Two-step header:
  1. **Source & scope**
  2. **Re-sync behavior**
- Completed steps display a success indicator.
- Current step uses the product accent.
- The native-ingestion notice appears prominently on step one.
- Advanced crawl settings are collapsed by default.
- Footer actions remain fixed and predictable.

The screenshots are structural references, not a new standalone visual system. Implementation must use the application's existing Dialog, buttons, fields, typography, spacing, focus behavior, and OSS/IBM brand tokens.

### 3.3 Step one: Source & scope

Fields:

- **Connection name**
- **Starting URL**
- **Crawl scope**
  - Path and children
  - This page only
  - Whole site
- **Allow subdomains**, off by default

Notice:

> URL ingestion always uses OpenRAG's native ingestion pipeline, even when Langflow ingestion is enabled for other sources.

Advanced crawl settings:

- Additional allowed hosts, one per line
- Include paths, one per line
- Exclude paths, one per line
- Change detection: **Normalized content hash**, read-only
- Maximum pages, default 250
- Maximum depth, default 4
- Maximum downloaded MB, default 128
- Maximum crawl minutes, default 15

The second numeric field in the third screenshot is interpreted as **Maximum depth**, not a duplicate Change detection field.

Always-on safety notice:

> OpenRAG identifies itself, honors robots.txt, restricts redirects and approved hosts, blocks private/internal destinations, limits crawl size and time, and runs asynchronously within OpenRAG's task system. These controls cannot be disabled.

Step-one validation:

- Name is required.
- Starting URL must be a valid public HTTP or HTTPS URL.
- Embedded credentials and IP-literal URLs are rejected.
- Only ports 80 and 443 are accepted.
- Additional hosts must be explicit hostnames.
- Include/exclude paths must begin with `/`.
- Page scope forces maximum pages to 1 and maximum depth to 0.
- Continue remains disabled until required inputs are valid.

### 3.4 Step two: Re-sync behavior

Re-sync behavior choices:

- **Full crawl; ingest returned pages**
- **Ingest only root page**

Removed-page choices:

- **Retain in corpus**
- **Delete**

Supporting copy must make clear that incomplete or capped crawls never delete missing pages.

Footer actions:

- **Cancel** closes without saving.
- **Back** returns to Source & scope without discarding values.
- **Ingest URL** creates the source and starts the asynchronous task.

### 3.5 Submission behavior

After successful submission:

1. Close the modal.
2. Remain on or return to `/knowledge`.
3. Immediately show the parent URL row in a processing state, using the same task/row behavior as other ingestion sources.
4. Register the task in task notifications.
5. Replace the processing state with active or failed when the task updates.

Double submission is prevented while the request is pending.

## 4. Knowledge page refactor

The URL child view must not introduce an independent table system. Refactor the current Knowledge page into reusable pieces first.

Proposed components:

- `KnowledgePageHeader`
  - Optional back button
  - Title
  - Optional right-aligned external/root link
  - Optional source-level actions
- `KnowledgeToolbar`
  - Backend search input
  - Filters/actions slots
  - Add Knowledge slot
- `KnowledgeDataTable`
  - Shared AG Grid setup
  - OSS/IBM row and header sizing
  - Loading and empty overlays
  - Selection behavior
  - Sort callbacks
  - Stable row identity
- `KnowledgePaginationFooter`
  - Existing component retained and shared
- Shared Knowledge column factory
  - Standard columns and formatters
  - Configurable title click behavior
  - Configurable action renderer
  - Optional URL/source-specific columns without forking the table implementation

The top-level Knowledge page must remain behaviorally unchanged for local and existing connector files.

## 5. Child-page view

### 5.1 Navigation and header

Opening a parent URL switches the Knowledge surface into a scoped child view, for example:

`/knowledge?website=<web_source_id>`

Header structure:

```text
[Back] Connection name                                  https://root.example/
```

- Back returns to the prior top-level Knowledge state.
- The root link appears on the right side of the same header row.
- The root link opens in a new tab with safe `rel` attributes.
- Source-level Sync and Delete are available in the header actions and/or the standard overflow action adjacent to the header.

### 5.2 Shared table behavior

The child view uses the extracted Knowledge components and the same:

- AG Grid implementation
- Backend search interaction
- Sorting behavior
- Pagination and page-size controls
- Loading, empty, failed, and processing states
- Status badges
- OSS and IBM brand behavior
- Accessible keyboard and focus behavior

Child rows represent real indexed documents. Clicking a row title opens:

`/knowledge/chunks?document_id=<child_document_id>`

The existing chunks page should accept stable document identity rather than relying only on a potentially duplicated display filename.

### 5.3 Columns

Use the Knowledge table's standard structure and behavior. For child pages, configure the columns to include:

- Title/name
- URL
- Size
- Type
- Owner
- Chunks
- Embedding model
- Dimensions
- Status
- Actions

The URL column links to the public page in a new tab. The title opens chunks inside OpenRAG.

Disabled children remain in the table, show a Disabled status, have no indexed chunks, and offer Re-sync rather than disappearing.

## 6. Data model

### 6.1 Website source

Persist:

- ID
- Workspace/owner identity
- Connection name
- Normalized starting URL
- Scope
- Allow-subdomains flag
- Additional hosts
- Include/exclude paths
- Maximum pages/depth/download/time
- Change-detection mode
- Re-sync behavior
- Removed-page behavior
- Status and last error
- Last task ID
- Last successful sync timestamp
- Created/updated timestamps

### 6.2 Website child page

Persist:

- ID
- Parent `web_source_id`
- Canonical URL
- Final URL after redirects
- Title/display filename
- Stable indexed document ID
- Content hash
- Depth
- Content type and byte size
- Chunk count/indexing metadata as needed
- Status
- `suppressed_by_user`
- Last seen and last ingested timestamps
- Last error

Constraints:

- Unique `(web_source_id, canonical_url)`.
- Stable child identity across syncs.
- Cascading relational deletion from parent to child records.

## 7. Canonical URL and content deduplication

Before queueing or ingesting a page:

1. Resolve relative URLs against the current page.
2. Permit only HTTP and HTTPS.
3. Normalize scheme and IDNA hostname casing.
4. Remove fragments.
5. Remove default ports.
6. Normalize empty paths and dot segments.
7. Apply the chosen query-string normalization policy consistently.
8. Resolve redirects and use the validated final canonical URL.
9. Deduplicate the crawl frontier by canonical URL.
10. Upsert by `(source ID, canonical URL)`.
11. Compute a hash from normalized extracted content.
12. Skip embedding and indexing when the stored hash is unchanged.
13. Replace the existing child document when the URL is unchanged but content changed.

Redirect aliases that lead to the same final URL produce one child item. Repeated links to the same URL never produce multiple children.

## 8. Crawl safety policy

Always enforced:

- `robots.txt`
- Identifiable OpenRAG user agent
- Public HTTP/HTTPS only
- No embedded credentials
- No IP-literal seeds or allowed-host entries
- No private, loopback, link-local, multicast, reserved, or internal destinations
- DNS answers fail closed if any resolved address is non-public
- Redirect targets are revalidated before following
- Same hostname by default
- Subdomains only when explicitly enabled
- Additional hosts only when explicitly listed
- No automatic cross-domain traversal
- Include/exclude path policy
- Maximum pages
- Shared maximum depth
- Maximum downloaded bytes
- Maximum crawl duration
- Per-response byte and redirect caps
- Cookies disabled
- Asynchronous execution through the task system

No deployment-changing sandbox requirement will be introduced. The UI and documentation must not claim sandbox isolation.

## 9. API plan

Source operations:

- `POST /connectors/url/sources`
- `GET /connectors/url/sources`
- `GET /connectors/url/sources/{source_id}`
- `POST /connectors/url/sources/{source_id}/sync`
- `DELETE /connectors/url/sources/{source_id}`

Child operations:

- `GET /connectors/url/sources/{source_id}/pages`
  - Backend search
  - Sort
  - Cursor/page pagination
  - Status filters
- `POST /connectors/url/sources/{source_id}/pages/{page_id}/sync`
  - Clears manual suppression
  - Fetches and re-ingests that page
- `DELETE /connectors/url/sources/{source_id}/pages/{page_id}`
  - Deletes chunks
  - Sets `suppressed_by_user=true`
  - Keeps the child record visible

Chunks/search changes:

- Support stable `document_id` when opening a child's chunks.
- Add `web_source_id`, `web_page_id`, `root_source_url`, and parent/source metadata to indexed documents and responses.
- Scope child search by source ID on the backend.
- Collapse child matches into their parent for top-level Knowledge results.

All endpoints enforce ownership/workspace boundaries and existing RBAC permissions.

## 10. Connector integration

Settings:

- URL appears under built-in connectors.
- It always displays as connected/active.
- It has no OAuth, credential configuration, or disconnect action.
- Its action is **Add Knowledge**, which opens the URL modal.

Add Knowledge dropdown:

- Label: **URL**
- Use the established URL icon.
- Use the same muted gray icon color as File and Folder.

Sync All:

- Includes all URL sources visible to the user/workspace.
- Runs each source using its saved re-sync behavior and safety limits.
- Skips sources already queued or syncing.

## 11. Failure and edge cases

- Source creation succeeds before the background crawl starts, allowing the processing parent row to exist immediately.
- A crawl that produces no indexable pages leaves the parent visible with a failed status and actionable error.
- A failed child sync preserves the previous indexed content unless the child was manually disabled.
- A page with `noindex` may be traversed when permitted but is not indexed.
- A page with `nofollow` is indexed when permitted but does not expand the frontier.
- Non-HTML content is skipped unless explicitly supported later.
- A title collision does not merge documents; stable identity uses source ID plus canonical URL.
- Concurrent root sync requests are rejected or coalesced.
- Parent deletion is blocked while a destructive conflict cannot be safely coordinated with an active task.
- Root-only sync does not reconcile or delete children.

## 12. Testing strategy

Backend unit tests:

- URL normalization
- Host/path scope boundaries
- Exact additional-host behavior
- Private/mixed DNS rejection
- Redirect revalidation
- Canonical frontier deduplication
- Redirect-alias deduplication
- Content-hash unchanged skip
- Changed-content replacement
- Robots/noindex/nofollow behavior
- Crawl limits and incomplete-crawl reconciliation guard
- Suppressed-child exclusion from root sync
- Manual child re-sync clearing suppression
- Parent cascade deletion

Backend integration tests:

- Create source and enqueue native task
- Parent processing/active/failed lifecycle
- Full versus root-only sync
- Retain versus delete reconciliation
- Scoped child search, sorting, and pagination
- Stable document ID chunks lookup
- Sync All URL-source scheduling
- RBAC and cross-owner isolation
- Migration upgrade/downgrade

Frontend unit tests with MSW:

- Settings connected state and Add Knowledge action
- Add Knowledge URL label and muted icon
- Modal two-step navigation and validation
- Advanced settings expansion
- Native and safety notices
- Submission closes modal and registers the task
- Parent icon badge and root URL tooltip
- Parent click opens child view
- Parent Sync/Delete from both locations
- Shared Knowledge table use in child view
- Backend child search and pagination payloads
- Child click opens chunks by document ID
- Disabled child remains visible
- Child Re-sync/Delete text-only menu
- OSS and IBM brand variants

Playwright coverage:

- Modal keyboard focus, Escape, and step navigation
- Parent-to-child-to-chunks navigation
- AG Grid geometry and responsive behavior
- Root/child destructive confirmation flows
- Processing row transition after modal submission

## 13. Implementation architecture and current-code analysis

### 13.1 URL is a managed connector, not a saved connection

The connector registry currently assumes that a connector is either `oauth` or `bucket`, and the frontend status query assumes it can look up a saved `connection_id`. URL does not fit either lifecycle: it has no OAuth handshake, credentials, configuration dialog, or disconnect operation, and one user may create many website sources.

Introduce a third connector kind, `managed`, plus an explicit `ALWAYS_CONNECTED`/`alwaysConnected` capability. The registry remains the source of truth for Settings and Add Knowledge, while website source records live in the database rather than `connections.json`.

Do not simulate an OAuth connection, create a fake connection ID, or store each website in `ConnectionManager`. Those approaches would incorrectly expose Connect/Disconnect behavior and make generic connector sync assume that one connector instance represents every website.

Registry consumers must be separated into two groups:

- **Connection-backed connectors:** OAuth and bucket connectors handled by `ConnectionManager` and the existing generic sync implementation.
- **Managed connectors:** URL, which supplies its own source CRUD and sync routes but still participates in connector discovery and workspace access policy.

### 13.2 Source records, page records, and the Knowledge parent projection

The current Knowledge list is built from OpenSearch chunk documents and `FileServiceV2` groups them by `filename`. Indexing each crawled page normally would therefore leak every page into the top-level table. Grouping all pages under the connection name would solve the parent row but break the child table and merge unrelated page titles.

Use three representations with deliberately different responsibilities:

1. `website_sources` SQL row: authoritative saved settings, owner, source status, active task/run, and reconciliation policy.
2. `website_pages` SQL row: authoritative child identity and lifecycle, including disabled pages that intentionally have no chunks.
3. One lightweight OpenSearch **source projection** document per parent, with `record_kind=web_source`: makes the parent participate in the existing Knowledge list, filters, DLS, sorting, and wildcard name search without merging SQL and OpenSearch pagination in the frontend.

Each real child chunk uses `record_kind=web_page`, `web_source_id`, `web_page_id`, a stable `document_id`, its own title/filename, and its own canonical URL. The normal Knowledge list adds a `must_not record_kind=web_page` clause, which preserves all legacy records lacking `record_kind` while hiding URL children. The child endpoint reads `website_pages`, so disabled children remain visible after their chunks are removed.

The projection document contains no embedding and must be excluded from semantic retrieval. Top-level semantic search still searches child chunks, then the backend collapses URL matches by `web_source_id` and returns the parent projection metadata with the best matching score. This avoids a fake embedded parent document and avoids duplicating the root page's content.

Projection fields:

- `record_kind=web_source`
- `document_id=web-source:<source_id>`
- `web_source_id`
- `filename=<connection name>`
- `source_url=<root URL>`
- `root_source_url=<root URL>`
- `connector_type=url`
- `web_child_count`
- parent status/error timestamps required by the table
- the same owner and ACL fields used by ordinary indexed documents

The projection is created in the same transaction boundary as source creation as far as practical. If OpenSearch projection creation fails after the SQL commit, the task records the failure and a repair/upsert is attempted on the next list or sync; SQL remains authoritative.

### 13.3 Stable child identity and replacement

The existing `process_document_standard` treats `file_hash` as both duplicate detector and indexed `document_id`. That is incompatible with website sync: a child must keep the same `document_id` when its content changes, while its normalized content hash must change.

Extend the native processor with a backward-compatible optional stable `document_id` and `replace_existing` switch:

- Existing callers continue using `file_hash` and the current early unchanged check.
- URL processing computes `document_id = sha256(web_source_id + "\0" + canonical_url)` once.
- URL orchestration compares the new normalized-content hash with `website_pages.content_hash` before invoking embeddings.
- An unchanged hash updates `last_seen_at` only and does not call the embedding/index writer.
- A changed page calls native processing with the stable document ID and `replace_existing=true`; stale chunks for that ID are removed before the new chunks are indexed.

The content hash is computed from normalized extracted Markdown, not response bytes, so harmless transport or HTML formatting changes do not cause a re-embed.

### 13.4 Native task lifecycle

Reuse `TaskService.create_custom_task`, `UploadTask`, `FileTask`, and `TaskProcessor` rather than creating a second background-job framework. Add a URL-specific processor that treats one source sync as the task item and reports phases through the existing task system.

The source row is created before the task starts, and its projection is written with `processing` status. This lets the existing task overlay and Knowledge refresh show the parent immediately.

The processor owns this sequence:

1. Load the source and acquire a per-source active-run guard.
2. Crawl with the immutable saved spec snapshot attached to the run.
3. Upsert discovered page records by canonical URL.
4. Skip user-disabled pages for ingestion.
5. Skip unchanged normalized content hashes.
6. Process changed/new pages through the native pipeline only.
7. Reconcile missing pages only if the full crawl completed without failure or a safety cap.
8. Update page/source states and the parent projection.
9. Release the active-run guard and complete/fail the existing task.

Add a small `website_crawl_runs` table rather than relying only on in-memory task state. It stores the settings snapshot, completion/capped flags, counts, task ID, and failure. This makes reconciliation decisions auditable and prevents a restarted process from mistaking an incomplete crawl for a complete one.

### 13.5 Child suppression state machine

Keep remote availability separate from user suppression:

| Event | `suppressed_by_user` | Chunks | Child row | Future root sync |
| --- | --- | --- | --- | --- |
| New page | `false` | Indexed | Active | Sync normally |
| User deletes child | `true` | Deleted | Disabled | Discover/traverse if needed, never ingest |
| User re-syncs child | cleared after fetch is accepted | Replaced | Processing → Active/Failed | Sync normally afterward |
| Missing + retain | unchanged | Retained | Unavailable/retained | Re-check next full crawl |
| Missing + delete | unchanged | Deleted | Record retained as removed for audit/UI policy | Recreate/re-ingest if rediscovered unless suppressed |
| Parent deleted | n/a | All deleted | All SQL rows cascaded | No future sync |

The single-page re-sync endpoint is the only implicit re-enable operation. Root sync, scheduled sync, and Sync All never clear suppression.

### 13.6 Search and chunks contracts

The existing list and chunks flows identify rows largely by filename. Website titles are not unique, so URL work must introduce stable identity without breaking older documents.

- `GET /api/v2/files` continues to return ordinary rows and parent projection rows; it excludes `record_kind=web_page` by default.
- `GET /connectors/url/sources/{source_id}/pages` performs server-side filtering, sorting, and pagination over `website_pages`, returning the same display row contract needed by `KnowledgeDataTable`.
- `/api/search` accepts a Knowledge result-view/scope parameter. Root mode collapses web-page hits to parents; child mode filters by `web_source_id` and groups by `document_id`/`web_page_id`, never filename.
- The chunks query accepts `document_id` and prefers it over the legacy filename filter. `filename` remains supported for old links.
- Chunks navigation carries `web_source_id` as a return context so Back returns to the child view.

## 14. File-by-file backend plan

### 14.1 Connector discovery and lifecycle

| File | Planned change | What is reused |
| --- | --- | --- |
| `src/connectors/base.py` | Document `managed` as a supported `CONNECTOR_KIND`; add `ALWAYS_CONNECTED = False` and a capability indicating whether the connector is connection-backed. | Existing connector metadata and `register_routes` extension point. |
| `src/connectors/registry.py` | Register `URLConnector`; add helpers that return all, connection-backed, or managed connector classes so callers do not infer lifecycle ad hoc. | Existing built-in/additional connector composition. |
| `src/connectors/url/__init__.py` | Export the URL connector. | Existing connector package convention. |
| `src/connectors/url/connector.py` | Define metadata (`url`, `URL`, description, icon, `managed`, always connected), always-available behavior, and `register_routes`. Implement unused abstract connector methods as explicit unsupported operations rather than fake remote-file methods. | `BaseConnector` and the existing route-registration hook. |
| `src/connectors/connection_manager.py` | Include `always_connected` in discovery metadata; never instantiate or persist managed connectors; make status for managed connectors deterministic if the generic status endpoint is called. | `get_available_connector_types` remains the single discovery source. |
| `src/services/auth_service.py` | Change `_data_source_connector_types()` to return only connection-backed kinds so `init_oauth` cannot create a URL connection. | Registry-derived validation. |
| `src/services/connector_access_service.py` | No URL special case; verify registry-derived `CONNECTOR_TYPES` makes URL governable under the existing workspace connector policy. Add tests for managed-kind visibility. | Existing access-map and SaaS enforcement. |
| `src/app/routes/internal.py` | No structural change expected; verify URL routes are registered through the existing connector-class loop. | Existing `register_routes` orchestration. |

### 14.2 Persistence

| File | Planned change | What is reused |
| --- | --- | --- |
| `src/db/models/website_source.py` | Add `WebsiteSource`, `WebsitePage`, and `WebsiteCrawlRun` SQLModel tables, enums/status strings, unique constraints, timestamps, owner/workspace fields, JSON crawl settings, and cascade relationships. | Current SQLModel conventions and UTC timestamp patterns. |
| `src/db/models/__init__.py` | Import/export all three models so SQLModel metadata and Alembic see them. | Existing model registration mechanism. |
| `src/db/repositories/website_source_repo.py` | Add ownership-scoped CRUD, paginated child search/sort, active-run locking, source/page state transitions, suppression, and reconciliation queries. | AsyncSession repository style; transactions remain owned by API/service layer. |
| `src/db/repositories/__init__.py` | Export `WebsiteSourceRepo`. | Existing repository barrel. |
| `alembic/versions/0008_website_sources.py` | Create source/page/run tables, `(web_source_id, canonical_url)` uniqueness, task/status indexes, owner indexes, and cascade foreign keys; include a clean downgrade. | Existing sequential migration structure. |

Store crawl configuration as validated JSON plus separately indexed operational columns. This keeps the spec round-trippable while avoiding a migration for every future optional crawler knob. Values needed in filters or invariants—IDs, status, suppression, canonical URL, task/run linkage—remain real columns.

### 14.3 Crawl policy, fetching, and conversion

| File | Planned change | What is reused |
| --- | --- | --- |
| `src/connectors/url/policy.py` | Add canonical URL/host/path normalization, `CrawlSpec`, host-scope matching, public-IP validation, redirect validation, cap validation, and query normalization. | Adapt the supplied `policy.py` functions and `CrawlSpec`; remove proxy-token signing/verification. |
| `src/connectors/url/fetcher.py` | Add an async safe fetcher with proxy environment disabled, validated DNS resolution, connection pinning to an approved public address while preserving hostname TLS verification/SNI, manual redirect handling, response limits, and cookies disabled. | Adapt destination authorization and validated-IP connection ideas from supplied `crawl_proxy.py`; do not run a proxy server. |
| `src/connectors/url/robots.py` | Fetch/cache `robots.txt` per approved host with the same safe fetcher, apply the OpenRAG user agent, and expose `can_fetch`/crawl-delay decisions. | Python robots parsing where sufficient; same safety policy for the robots request itself. |
| `src/connectors/url/document.py` | Convert supported HTML/XHTML into inert normalized Markdown; return title, canonical content, byte count, and normalized-content hash. | Adapt `SimpleHTMLToMarkdown` and `html_to_markdown_document` from the supplied `document.py`. |
| `src/connectors/url/crawler.py` | Implement breadth-first frontier, shared depth, canonical-URL dedupe, link extraction, nofollow/noindex, scope checks, caps, completion reason, and per-page outcomes. | Adapt the supplied runner's crawl/frontier behavior; run in the existing task process rather than Scrapy CLI/sandbox. |

The direct fetcher is the safety boundary because the deployment will not add a crawler sandbox or egress proxy. Validation must occur again for every redirect and every DNS resolution, not only when the form is submitted. An ordinary `httpx.get(validated_url)` after a DNS check is insufficient because it is vulnerable to DNS rebinding; the implementation must connect to a validated address while retaining hostname TLS validation.

### 14.4 Orchestration, task processing, and indexing

| File | Planned change | What is reused |
| --- | --- | --- |
| `src/connectors/url/service.py` | Coordinate create/list/get, task enqueueing, projection repair, source sync, page sync, suppression, parent cascade delete, and ownership/RBAC checks. Keep policy and persistence details out of route handlers. | Service/repository separation already used in backend modules. |
| `src/connectors/url/processor.py` | Add the `TaskProcessor` implementation for root and single-page sync, saved-spec snapshots, page upserts, content-hash skip, native ingestion, reconciliation, and projection updates. | `TaskProcessor`, `UploadTask`, `FileTask`, and native processing. |
| `src/connectors/url/projection.py` | Upsert/delete the non-vector parent projection and update child counts/status with the trusted backend OpenSearch client. | Existing DLS owner/ACL field conventions and concrete-ID deletion utilities. |
| `src/connectors/url/api.py` | Define Pydantic request/response schemas and register source/page CRUD and sync endpoints with current permission dependencies. | Connector `register_routes`, `require_permission`, DB session, current-user patterns. |
| `src/services/task_service.py` | Add `create_website_source_task` and `create_website_page_task`, both thin wrappers around `create_custom_task`; ensure file-task metadata exposes the source name/URL and connector type for the processing row. | Existing task store, notifications, scheduling, cancellation, and progress lifecycle. |
| `src/models/processors.py` | Add optional stable `document_id`, `source_url`, URL metadata, and `replace_existing` behavior to `process_document_standard`; preserve defaults for every existing caller. | Plain-text fast path, chunking, embedding calls, stale-chunk cleanup, ACL resolution, and `DocumentIndexWriter`. |
| `src/services/document_index_writer.py` | Extend `DocumentIndexContext` and top-level chunk fields with `record_kind`, `web_source_id`, `web_page_id`, `root_source_url`, and canonical URL. | Central trusted bulk writer and scoped chunk IDs. |
| `src/config/settings.py` | Add explicit keyword mappings for the new identity fields and numeric/date mappings for projected child count/status timestamps. Add hard server ceilings separately from per-source user-selected values. | `INDEX_BODY` and existing env helper functions. |
| `src/utils/opensearch_init.py` | Add the new fields to startup mapping reconciliation for existing indices. | `_ensure_keyword_mappings` and `_ensure_field_mappings`; no reindex required for legacy documents. |
| `src/utils/opensearch_delete.py` | Add or reuse query-scoped deletion helpers for stable child document IDs and whole `web_source_id` deletion without accepting arbitrary client queries. | Visible-ID collection plus trusted concrete deletion. |

`src/models/url.py` and `utils.url_content_fetcher.materialize_url_as_text_file` should remain for existing OpenRAG sample-doc/MCP URL behavior. They must not be expanded into the connector because they combine a crawl into one text file, lack persistent page identity, and do not implement source/page sync semantics.

### 14.5 Listing, search, sync-all, and chunks

| File | Planned change | What is reused |
| --- | --- | --- |
| `src/services/file_service_v2.py` | Exclude `record_kind=web_page` in the default/root view, include projection metadata in `top_hits`, parse URL parent fields, and preserve legacy documents with no `record_kind`. | Composite aggregation, cursor pagination, filtering, global sorting, and chunk-count fallback. |
| `src/api/v2/files.py` and/or the current files route module | Add the view/scope parameter and serialize URL parent metadata without changing default clients. | Existing list endpoint and auth dependencies. |
| `src/services/search_service.py` | Add indexed URL metadata to hits; implement root-result collapse by `web_source_id`; allow child scope by source/document ID; exclude source projections from vector retrieval. | Existing embedding retrieval, DLS user client, score handling, and filters. |
| `src/api/search.py` | Extend `SearchBody` with optional `result_view`/`web_source_id`; validate that child scope is owned/visible before searching. | Current search endpoint. |
| `src/api/connectors.py` | Make `_cloud_connector_types()` return connection-backed connectors only; append URL-source tasks to Sync All through `URLSourceService`; include URL in sync preview with source/page counts and “updates unavailable until crawl” semantics where exact changes require fetching. | Existing Sync All response, partial-error behavior, telemetry, permission gates, and task ID aggregation. |
| Existing chunks/search filter helpers | Permit a stable `document_id` term and `web_source_id` return context. | Existing DLS-safe user OpenSearch client and query-building patterns. |

Do not put URL inside `_sync_existing_connector_files`: that function assumes one working `ConnectionConfig`, a remote file listing, and connector file IDs. URL sync has multiple saved sources, crawl completeness, suppression, and per-source policy, so forcing it through that abstraction would add brittle branches throughout the generic connector path.

### 14.6 Backend function-level reuse and extraction

Extend current seams instead of copying their internals:

| Current function/class | Plan |
| --- | --- |
| `BaseConnector.register_routes` | Reuse unchanged to mount URL-owned routes. This keeps the main router free of connector-specific endpoint imports. |
| `ConnectionManager.get_available_connector_types` | Extend its returned metadata only. Do not create a parallel `/url/metadata` discovery request. |
| `_cloud_connector_types` in `src/api/connectors.py` | Rename or narrow it to `connection_backed_connector_types`; add a separate `_sync_managed_url_sources` helper called by Sync All. This makes the lifecycle distinction explicit. |
| `TaskService.create_custom_task` | Keep all task creation/storage/scheduling here. New URL task methods should only construct processors/items/labels. |
| `TaskProcessor.process_document_standard` | Reuse conversion, chunking, embedding, ACL, and writer behavior. Add stable identity/replacement parameters; do not reproduce this pipeline in the URL processor. |
| `DocumentIndexWriter.index_chunks` | Reuse for real child chunks. Keep source-projection writes in a separate small writer because `index_chunks` correctly requires embeddings. |
| `FileServiceV2._build_filter_query` | Add a server-owned record-view clause and optional `web_source_id`; do not expose raw OpenSearch predicates to clients. |
| `FileServiceV2._build_composite_aggregation` and `_buckets_to_files` | Extend metadata sources/parsing for parent projection fields. Preserve the existing cursor and chunk-count algorithms. |
| `SearchService.search` | Add scope/filter inputs and call a new pure `collapse_website_hits(hits, source_metadata)` helper after retrieval. The helper can be unit-tested independently and must preserve non-URL hit ordering. |
| Existing OpenSearch visible-ID/deletion helpers | Compose `delete_child_document(document_id)` and `delete_source_documents(web_source_id)` from fixed term queries. Do not add a generic user-supplied delete-by-query endpoint. |

New URL package functions should remain small and separately testable:

- `canonicalize_url(value) -> str`
- `normalize_host(value) -> str`
- `normalize_path_prefix(value) -> str`
- `is_public_ip(value) -> bool`
- `resolve_public_addresses(host, port) -> tuple[str, ...]`
- `derive_allowed_hosts(seed, allow_subdomains, additional_hosts) -> tuple[str, ...]`
- `CrawlSpec.allows_url(url) -> bool`
- `stable_page_document_id(source_id, canonical_url) -> str`
- `normalized_content_hash(markdown) -> str`
- `reconciliation_action(page, run, removed_page_policy) -> retain | delete | none`
- `should_ingest_page(page, new_hash) -> new | changed | unchanged | suppressed`

The crawler itself should depend on injected `SafeFetcher` and robots interfaces. Unit tests can then exercise traversal and reconciliation with deterministic responses without opening sockets.

## 15. File-by-file frontend plan

### 15.1 Registry, Settings, and Add Knowledge

| File | Planned change | What is reused/extracted |
| --- | --- | --- |
| `frontend/lib/connectors/types.ts` | Extend `ConnectorKind` with `managed`; add `alwaysConnected` and a declarative Add Knowledge action mode (`route` or `dialog`) to the descriptor. | Existing descriptor-driven UI; prevents repeated `connectorType === "url"` branches. |
| `frontend/lib/connectors/registry.ts` | Register URL with the existing URL/Globe icon, display name `URL`, managed kind, and dialog action. | Existing registry lookup and icon type. |
| `frontend/app/api/queries/useGetConnectorsQuery.ts` | Map `always_connected`; skip per-connection status fetch for managed connectors and expose them as connected without a connection ID. | Existing discovery request, deployment filtering, and React Query cache. |
| `frontend/app/settings/_components/connector-card.tsx` | Render managed connected state; keep Add Knowledge; hide Configure/Disconnect and connection-ID assumptions. | Existing card layout, permission state, and OSS/IBM tokens. |
| `frontend/app/settings/_components/connector-cards.tsx` | Add a managed/built-in group and dispatch descriptor actions; URL opens `/knowledge?add=url` or the shared modal controller. | Existing connector grouping and Settings page composition. |
| `frontend/components/knowledge-dropdown.tsx` | Add `URL` from the registry, use the same muted icon wrapper as File/Folder, and open the modal. Mount one controlled modal instance rather than rendering source history. | Existing dropdown, permissions, Dialog primitives, and task context. |
| `frontend/app/upload/[provider]/page.tsx` | Add only a compatibility redirect from `url` to `/knowledge?add=url`; do not build a URL upload page. | Existing route boundary. |

### 15.2 Modal and frontend API layer

| File | Planned change | What is reused/extracted |
| --- | --- | --- |
| `frontend/components/connectors/url/url-source-dialog.tsx` | New two-step modal shell matching the screenshots, native-ingestion notice, fixed footer, focus/close behavior, and submission lifecycle. | `Dialog`, `Button`, app typography/spacing, OSS/IBM brand tokens. |
| `frontend/components/connectors/url/url-source-form.tsx` | New controlled form for scope cards, subdomain switch, advanced accordion, limits, and re-sync options. Keep visual state separate from network mutation. | `Input`, `Label`, `Textarea`, `Switch`, `Collapsible`; no bespoke design system. |
| `frontend/components/connectors/url/url-form-state.ts` | Pure defaults, newline parsing, scope-derived settings, unit conversions, and client validation. | Adapt `emptyForm`, `specFromForm`, and `lines` from supplied `WebSourcesFeature.tsx`; correct page scope to depth `0`. |
| `frontend/app/api/queries/useWebsiteSources.ts` | Query source/children and expose source/page sync/delete mutations with cache invalidation. | React Query conventions and real network mocking in tests. |
| `frontend/app/api/mutations/useCreateWebsiteSource.ts` | Create source, receive task ID/source row, add the task to context, invalidate Knowledge, and close only on success. This may live with the query module if repository convention favors one file. | Existing mutation/task notification patterns. |

Form validation must also run on the backend. Frontend validation exists for immediate feedback and button state, not as a security control.

### 15.3 Knowledge-page extraction boundaries

`frontend/app/knowledge/page.tsx` currently owns fetching, cursor state, task overlay merging, permissions, a large inline column definition, brand-specific toolbar branches, and two almost-identical `AgGridReact` trees. Extract in this order so each commit can prove no behavior regression before URL behavior is added.

| New/existing file | Responsibility | Explicitly keep out |
| --- | --- | --- |
| `frontend/components/knowledge/knowledge-page-header.tsx` | Shared header layout with optional Back, title, external root link, and source action slot. | Fetching, route parsing, or source mutations. |
| `frontend/components/knowledge/knowledge-toolbar.tsx` | Shared placement of search, filters, status text, Sync, and Add Knowledge slots while retaining IBM/OSS variants. | Search state ownership and API requests. |
| `frontend/components/knowledge/knowledge-data-table.tsx` | The single AG Grid instance, grid refs, OSS/IBM sizing/class differences, loading/empty overlays, selection callbacks, and stable row ID. | Data fetching, delete/sync mutations, URL-specific rules. |
| `frontend/components/knowledge/use-knowledge-columns.tsx` | Column factory/hook receiving title renderer/click handler, action renderer, row-selectability, and view-specific optional fields. | Network calls; pass callbacks from the controller. |
| `frontend/hooks/use-knowledge-pagination.ts` | Cursor cache, page/page-size, sort reset, filter reset, and next/previous behavior currently inline in the page. | Knowledge row transformation or API endpoint choice. |
| `frontend/hooks/use-knowledge-table-data.ts` | Choose wildcard list versus semantic search, accept a root/child scope, normalize response rows, and expose loading/error/refetch. | AG Grid presentation and destructive actions. |
| `frontend/lib/knowledge-table-state.ts` | Extend the existing pure module with selection equality/pruning, row identity, task-overlay identity, and sort-field mapping. | React state, router, and mutation side effects. |
| `frontend/components/knowledge-pagination-footer.tsx` | Keep and reuse without a URL fork. | URL-specific pagination logic. |

The column hook is necessary because the existing columns close over router, permissions, task cancellation, connector sync, delete state, and brand. A static shared array would either lose those dependencies or become a global mutable object. The table component should receive already-built columns and rows.

The data hook may share the request-selection logic, but task-overlay merging remains configurable:

- Root view uses `buildKnowledgeTableRows` so newly submitted sources appear immediately.
- Child view uses persisted page rows and only overlays tasks scoped to the same `web_source_id`.
- Never merge all global task files into the child view; filenames and URLs can collide across sources.

### 15.4 Parent and child views

| File | Planned change | What is reused/extracted |
| --- | --- | --- |
| `frontend/app/knowledge/page.tsx` | Become the route/controller: parse `website` and `add=url`, choose root or `WebsiteChildrenView`, own shared dialogs and high-level mutations, and compose extracted components. | Existing permissions, filter context, task context, and page behavior. |
| `frontend/components/connectors/url/website-parent-cell.tsx` | Render the established URL icon, bottom-right numeric child badge, name-only row, URL tooltip, and child-view navigation. | Existing `getSourceIcon` result and standard title styles; do not introduce a new icon. |
| `frontend/components/connectors/url/website-children-view.tsx` | Load one owned source and paginated children, render shared header/toolbar/table/footer, expose source Sync/Delete in the header, and navigate child titles to chunks. | All extracted Knowledge surface components. |
| `frontend/components/knowledge-actions-dropdown.tsx` | Extract the generic ellipsis trigger/menu shell and add typed row action composition. Keep existing cloud sync preview behavior intact. | Existing dropdown placement, text styling, permission/disabled behavior. |
| `frontend/components/connectors/url/website-actions-dropdown.tsx` | Compose text-only parent or child actions: Open pages/View chunks, Sync/Re-sync, Delete/Disable. | Shared action-menu shell and `DeleteConfirmationDialog`; no icons in child actions. |
| `frontend/components/ui/status-badge.tsx` | Add `disabled`, `retained`, and URL crawl states only if those states are returned to the table; keep labels in the central config. | Existing badge typography and colors. |
| `frontend/app/api/queries/useListFiles.ts` | Map `document_id`, `record_kind`, URL parent metadata, child count, and status; pass root result-view parameters. | Existing pagination/filter query key and response mapping. |
| `frontend/app/api/queries/useGetSearchQuery.ts` | Send the requested result view/source scope; consume backend-collapsed parent results; group children by stable document/page ID rather than filename. | Existing semantic search flow and score threshold. |
| `frontend/lib/file-chunks.ts` | Add a stable-document query builder while preserving `fileScopedSearchQueryData(filename)` for legacy routes. | Existing parsed-filter shape. |
| `frontend/app/api/queries/useFileScopedChunksQuery.ts` | Accept `{documentId, filename}` and prefer document ID. | Existing query/cache behavior. |
| `frontend/app/knowledge/chunks/page.tsx` | Read `document_id`, display the child filename, and return to `/knowledge?website=<id>` when the source context is present. | Existing chunks header/table and fallback `/knowledge` back behavior. |

The parent icon badge is a presentation of `web_child_count` returned by the backend. The browser should not fetch all children merely to count them.

### 15.5 Exact extractions from the current Knowledge page

The following symbols currently live in `frontend/app/knowledge/page.tsx` or are tightly coupled to it. Move or reshape them before adding the child view:

| Current code | Destination and change |
| --- | --- |
| `sameFileSelection` | Move unchanged to `frontend/lib/knowledge-table-state.ts`; generalize its identity comparison to prefer `document_id`/`web_source_id` before filename. |
| `syncGridSelectionToDeletableRows` | Move to `knowledge-table-state.ts` as a pure grid-selection adapter, or keep it private to `KnowledgeDataTable` if it still requires the AG Grid API. It must accept a row-selectability predicate rather than knowing deletion rules. |
| `pruneNonDeletableGridSelection` | Move beside the selection sync helper and parameterize eligibility. Root and child views have different delete semantics. |
| `getSourceIcon` | Extract to `frontend/components/knowledge/knowledge-source-icon.tsx`; preserve the existing URL glyph, dimensions, and color. Add an optional count-badge slot used only by URL parents. Both root and child tables call this component instead of duplicating connector icon switches. |
| `AG_FIELD_TO_SORT_BY` | Move to `knowledge-table-state.ts` or the pagination hook as an immutable mapping. The column factory exposes stable field IDs that map through it. |
| `listFilesFilterValues` | Move to `use-knowledge-table-data.ts` as a pure conversion from filter context to API values. Add the view/source scope separately so it never leaks into user-selected filters. |
| `buildFilterPageResetKey` | Move to `use-knowledge-pagination.ts`; include result view and `web_source_id` so entering/leaving a child view resets cursors correctly. |
| Inline cursor cache/page/sort effects | Encapsulate in `useKnowledgePagination`. The hook returns request cursor plus event handlers; it does not fetch. |
| Inline wildcard-versus-semantic query choice | Encapsulate in `useKnowledgeTableData`. Root and child controllers supply the scope and receive normalized rows. |
| `columnDefs` block | Split into `useKnowledgeColumns` plus small cell renderers. The title cell accepts `onOpenRow`; the actions cell accepts a renderer; the icon cell uses `KnowledgeSourceIcon`. |
| The two `AgGridReact` branches | Replace with one `KnowledgeDataTable` and computed brand props (`headerHeight`, `rowHeight`, class/border, selection options). This is the key guarantee that the child page uses the exact same table. |
| IBM `KnowledgeSearchBar` / OSS `KnowledgeSearchInput` branch | Keep both existing components and place the branch inside `KnowledgeToolbar`; do not merge their distinct design behaviors. |
| `buildKnowledgeTableRows` | Keep in the existing library and extend row identity/task metadata. Root uses it directly; child supplies a scoped overlay list. |
| `KnowledgePaginationFooter` | Reuse as-is and feed it the extracted pagination controller. |

Avoid one giant “reusable Knowledge page” component with dozens of booleans. The intended split is controller hooks + small layout components + one table component. Root and child views compose those pieces with different row/action policies.

### 15.6 Frontend pure functions and contracts

Add testable pure functions rather than embedding form and URL behavior inside JSX:

- `emptyUrlSourceForm()`
- `linesToValues(text)`
- `deriveScopeDefaults(startingUrl, scope)`
- `urlSourcePayloadFromForm(form)`
- `validateUrlSourceForm(form)` for UX feedback only
- `knowledgeRowId(row)` preferring source/page/document IDs
- `knowledgeRouteForRow(row)` returning child view or chunks destination
- `urlParentTooltip(row)` returning only the root URL
- `mergeScopedTaskRows(indexedRows, taskRows, scope)`

The server remains authoritative for canonicalization, public-network checks, limits, ownership, and suppression state.

## 16. Reuse assessment of the supplied product files

| Supplied file | Reuse directly or adapt | Do not carry over |
| --- | --- | --- |
| `/Users/lucas/Downloads/policy.py` | Adapt `normalize_host`, `normalize_url`, `public_ip`, `resolve_public_addresses`, `host_matches`, path-prefix helpers, and most of `CrawlSpec` validation. These are the strongest reusable parts. | Signed proxy-policy tokens and wildcard additional-host behavior unless product rules explicitly allow wildcards. The new form says explicit hosts; subdomains are controlled by the dedicated toggle. |
| `/Users/lucas/Downloads/document.py` | Adapt the dependency-free HTML-to-Markdown conversion, title extraction, inert output, whitespace normalization, and empty-content rejection. Hash its normalized output. | Treating this minimal parser as a full readability engine; richer extraction can be a later replaceable adapter. |
| `/Users/lucas/Downloads/crawl_runner.py` | Adapt BFS/depth/frontier behavior, robots handling, redirect scope checks, manifest/page outcome concepts, content-type gating, and total caps. | Scrapy process entry point, sandbox workspace paths, proxy configuration, and file manifest as the primary internal interface. |
| `/Users/lucas/Downloads/crawl_proxy.py` | Adapt the rule that every destination is authorized after resolving exclusively public addresses and that the actual connection uses one of those approved addresses. | The standalone CONNECT/HTTP proxy server, bearer policy headers, and deployment requirement for an egress proxy. |
| `/Users/lucas/Downloads/application.py` | Adapt name/spec validation, ownership checks, one-active-crawl guard, safe public error messages, explicit crawl/ingest phases, and output-integrity mindset. | In-memory `_jobs`, `ThreadPoolExecutor`, Kubernetes adapter, sandbox requirement, temp manifest handoff, and the behavior that deletion leaves corpus documents behind. OpenRAG's parent delete must cascade. |
| `/Users/lucas/Downloads/ports.py` | Keep the interface ideas useful for testing a crawler implementation, possibly as a small `Crawler`/`SafeFetcher` protocol. | `CrawlerSandbox` itself, because no separate sandbox runtime is planned. |
| `/Users/lucas/Downloads/WebSourcesFeature.tsx` | Adapt form defaults, field-to-spec conversion, scope derivation, newline parsing, async phase labels, and the separation between controller state and render surface. | Its custom CSS/classes, standalone source list, source settings UI, PII controls, polling loop, Save-only path, isolated-sandbox copy, and its current delete semantics. The requested experience uses OpenRAG's Dialog, React Query/task context, and Knowledge page. |

Code should be copied only after reconciling these semantic differences:

- Supplied page scope currently produces depth `1`; this feature requires no followed links, so persist depth `0` and maximum pages `1`.
- Supplied additional hosts accept `*.host`; the requested form uses explicit hostnames, while “Allow subdomains” is the only wildcard-like control.
- Supplied deletion disconnects a source but retains corpus data; requested root deletion removes source, children, and chunks.
- Supplied source sync turns a crawl into a batch of connector documents but does not retain child suppression or removed-page reconciliation state.
- Supplied copy claims an isolated sandbox; the new UI must instead say it runs asynchronously within OpenRAG's task system.

## 17. Embedded source-derived implementation reference

This section makes the plan executable without access to the originally supplied files. The code is copied or adapted from those files and is the implementation seed for OpenRAG. Namespaces and dependencies must be adjusted to the repository, but the security and behavioral invariants shown here must be preserved.

### 17.1 Reuse rules

- **Use directly after moving into the named target module:** normalization, public-address checks, path matching, basic HTML-to-Markdown conversion, form defaults, newline parsing, and unit conversions.
- **Adapt around OpenRAG interfaces:** crawler traversal, task creation, owner checks, and active-run locking.
- **Preserve the invariant, not the old runtime:** validated-address connection, redirect revalidation, robots behavior, caps, and safe errors.
- **Do not copy:** proxy-policy signing, standalone proxy server, Kubernetes sandbox calls, `ThreadPoolExecutor`, in-memory jobs, custom CSS, or standalone source-list UI.

### 17.2 Crawl policy core

Target: `src/connectors/url/policy.py`

Derived from the supplied `policy.py`. This block is intended to be copied into the feature, then integrated with repository logging and tests. The dedicated subdomain toggle is represented internally as `*.seed-host`; user-entered additional hosts remain exact names.

```python
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import posixpath
import socket
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class CrawlPolicyError(ValueError):
    """A source or destination violates the URL connector policy."""


def normalize_host(value: str) -> str:
    host = value.strip().rstrip(".").lower()
    if not host:
        raise CrawlPolicyError("URL must include a hostname")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise CrawlPolicyError("URL hostname is invalid") from exc
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    raise CrawlPolicyError("IP-literal URLs are not permitted for URL sources")


def _normalize_query(query: str) -> str:
    """Apply one deterministic query policy for frontier deduplication.

    This preserves duplicate keys and values while sorting pairs. If product
    policy later strips known tracking parameters, add that rule here only so
    create, crawl, redirect handling, and sync continue to agree.
    """
    if not query:
        return ""
    return urlencode(sorted(parse_qsl(query, keep_blank_values=True)), doseq=True)


def normalize_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
    except ValueError as exc:
        raise CrawlPolicyError("URL is invalid") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise CrawlPolicyError("URL sources support only http and https URLs")
    if parsed.username is not None or parsed.password is not None:
        raise CrawlPolicyError("URLs with embedded credentials are not permitted")
    host = normalize_host(parsed.hostname or "")
    try:
        port = parsed.port
    except ValueError as exc:
        raise CrawlPolicyError("URL port is invalid") from exc
    if port is not None and port not in {80, 443}:
        raise CrawlPolicyError("URL sources support only ports 80 and 443")
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if port is None or default_port else f"{host}:{port}"
    raw_path = parsed.path or "/"
    trailing_slash = raw_path.endswith("/")
    path = posixpath.normpath(raw_path)
    if not path.startswith("/"):
        path = "/" + path
    if trailing_slash and path != "/":
        path += "/"
    return urlunsplit((scheme, netloc, path, _normalize_query(parsed.query), ""))


def public_ip(value: str) -> bool:
    """Return true only for a globally routable address."""
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if address in ipaddress.ip_network("100.64.0.0/10"):
        return False
    return address.is_global


def resolve_public_addresses(host: str, port: int) -> tuple[str, ...]:
    """Resolve a destination and fail closed if any answer is unsafe."""
    normalized = normalize_host(host)
    try:
        records = socket.getaddrinfo(normalized, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise CrawlPolicyError("destination hostname could not be resolved") from exc
    addresses = tuple(dict.fromkeys(record[4][0] for record in records))
    if not addresses or any(not public_ip(address) for address in addresses):
        raise CrawlPolicyError("destination does not resolve exclusively to public addresses")
    return addresses


def host_matches(host: str, allowed_hosts: Iterable[str]) -> bool:
    normalized = normalize_host(host)
    for candidate in allowed_hosts:
        item = str(candidate).strip().lower()
        if item.startswith("*."):
            suffix = normalize_host(item[2:])
            if normalized.endswith("." + suffix):
                return True
        elif normalized == normalize_host(item):
            return True
    return False


def derive_allowed_hosts(
    seed_url: str,
    *,
    allow_subdomains: bool,
    additional_hosts: Iterable[str],
) -> tuple[str, ...]:
    seed_host = normalize_host(urlsplit(normalize_url(seed_url)).hostname or "")
    values = [seed_host]
    if allow_subdomains:
        values.append(f"*.{seed_host}")
    for value in additional_hosts:
        item = str(value).strip()
        if not item:
            continue
        if item.startswith("*."):
            raise CrawlPolicyError(
                "Additional allowed hosts must be exact; use Allow subdomains for the seed host"
            )
        values.append(normalize_host(item))
    return tuple(dict.fromkeys(values))


def _normalize_path_prefix(value: str) -> str:
    path = value.strip()
    if not path.startswith("/"):
        raise CrawlPolicyError("crawl path prefixes must begin with /")
    if "?" in path or "#" in path:
        raise CrawlPolicyError("crawl path prefixes cannot contain a query or fragment")
    return path


def _path_matches(path: str, prefix: str) -> bool:
    if prefix == "/":
        return True
    normalized = prefix.rstrip("/")
    return path == normalized or path.startswith(normalized + "/")


@dataclass(frozen=True)
class CrawlSpec:
    seed_url: str
    allowed_hosts: tuple[str, ...]
    include_path_prefixes: tuple[str, ...] = ("/",)
    exclude_path_prefixes: tuple[str, ...] = ()
    max_pages: int = 250
    max_depth: int = 4
    max_total_bytes: int = 128 * 1024 * 1024
    timeout_seconds: int = 15 * 60
    scope: str = "path"

    def __post_init__(self) -> None:
        seed = normalize_url(self.seed_url)
        parsed = urlsplit(seed)
        allowed = tuple(
            dict.fromkeys(
                "*." + normalize_host(str(item)[2:])
                if str(item).startswith("*.")
                else normalize_host(str(item))
                for item in self.allowed_hosts
            )
        )
        if not allowed:
            allowed = (normalize_host(parsed.hostname or ""),)
        if not host_matches(parsed.hostname or "", allowed):
            raise CrawlPolicyError("seed URL must be within the allowed hostname scope")
        includes = tuple(_normalize_path_prefix(item) for item in self.include_path_prefixes) or ("/",)
        excludes = tuple(_normalize_path_prefix(item) for item in self.exclude_path_prefixes)
        if not (1 <= self.max_pages <= 10_000):
            raise CrawlPolicyError("max_pages must be between 1 and 10000")
        if not (0 <= self.max_depth <= 20):
            raise CrawlPolicyError("max_depth must be between 0 and 20")
        if not (1 <= self.max_total_bytes <= 2 * 1024 * 1024 * 1024):
            raise CrawlPolicyError("max_total_bytes exceeds the permitted limit")
        if not (30 <= self.timeout_seconds <= 3600):
            raise CrawlPolicyError("timeout_seconds must be between 30 and 3600")
        if self.scope not in {"page", "path", "site"}:
            raise CrawlPolicyError("scope must be page, path, or site")
        if self.scope == "page" and (self.max_pages != 1 or self.max_depth != 0):
            raise CrawlPolicyError("page scope requires max_pages=1 and max_depth=0")
        object.__setattr__(self, "seed_url", seed)
        object.__setattr__(self, "allowed_hosts", allowed)
        object.__setattr__(self, "include_path_prefixes", includes)
        object.__setattr__(self, "exclude_path_prefixes", excludes)

    def allows_url(self, value: str) -> bool:
        try:
            parsed = urlsplit(normalize_url(value))
        except CrawlPolicyError:
            return False
        path = parsed.path or "/"
        return (
            host_matches(parsed.hostname or "", self.allowed_hosts)
            and any(_path_matches(path, prefix) for prefix in self.include_path_prefixes)
            and not any(_path_matches(path, prefix) for prefix in self.exclude_path_prefixes)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "seed_url": self.seed_url,
            "allowed_hosts": list(self.allowed_hosts),
            "include_path_prefixes": list(self.include_path_prefixes),
            "exclude_path_prefixes": list(self.exclude_path_prefixes),
            "max_pages": self.max_pages,
            "max_depth": self.max_depth,
            "max_total_bytes": self.max_total_bytes,
            "timeout_seconds": self.timeout_seconds,
            "scope": self.scope,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CrawlSpec":
        return cls(
            seed_url=str(value.get("seed_url") or ""),
            allowed_hosts=tuple(str(item) for item in value.get("allowed_hosts") or ()),
            include_path_prefixes=tuple(
                str(item) for item in value.get("include_path_prefixes") or ("/",)
            ),
            exclude_path_prefixes=tuple(
                str(item) for item in value.get("exclude_path_prefixes") or ()
            ),
            max_pages=int(value.get("max_pages", 250)),
            max_depth=int(value.get("max_depth", 4)),
            max_total_bytes=int(value.get("max_total_bytes", 128 * 1024 * 1024)),
            timeout_seconds=int(value.get("timeout_seconds", 15 * 60)),
            scope=str(value.get("scope") or "path"),
        )
```

Server-configured hard ceilings must be applied before constructing `CrawlSpec`; the model's absolute limits are defense in depth, not tenant-specific configuration.

### 17.3 HTML normalization and content hashing

Target: `src/connectors/url/document.py`

Copied from the supplied `document.py`, with the normalized hash added so the same output drives change detection and ingestion.

```python
from __future__ import annotations

import hashlib
from html import unescape
from html.parser import HTMLParser
import re


class SimpleHTMLToMarkdown(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style"}:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in {"p", "div", "section", "article", "header", "footer", "tr"}:
            self._newline()
        elif tag == "br":
            self._parts.append("\n")
        elif tag == "li":
            self._newline()
            self._parts.append("- ")
        elif re.fullmatch(r"h[1-6]", tag):
            self._newline()
            self._parts.append("#" * int(tag[1]) + " ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag in {
            "p", "div", "section", "article", "header", "footer", "li", "tr"
        } or re.fullmatch(r"h[1-6]", tag):
            self._newline()

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = re.sub(r"\s+", " ", unescape(data)).strip()
        if not text:
            return
        if self._parts and not self._parts[-1].endswith((" ", "\n", "- ")):
            self._parts.append(" ")
        self._parts.append(text)

    def markdown(self) -> str:
        text = "".join(self._parts)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _newline(self) -> None:
        if not self._parts:
            return
        current = "".join(self._parts)
        if current.endswith("\n\n"):
            return
        self._parts.append("\n" if current.endswith("\n") else "\n\n")


def html_to_markdown_document(
    content: bytes,
    *,
    encoding: str = "utf-8",
    source_url: str = "",
) -> tuple[str, str]:
    """Return `(title, normalized_markdown)` for one untrusted page."""
    text = content.decode(encoding or "utf-8", errors="replace")
    title_match = re.search(
        r"<title(?:\s[^>]*)?>(.*?)</title\s*>",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    title = ""
    if title_match:
        title = re.sub(r"<[^>]+>", " ", unescape(title_match.group(1)))
        title = re.sub(r"\s+", " ", title).strip()
    body_html = re.sub(
        r"<head(?:\s[^>]*)?>.*?</head\s*>",
        "",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    parser = SimpleHTMLToMarkdown()
    parser.feed(body_html)
    body = parser.markdown().strip()
    if not body:
        raise ValueError("HTML document produced no extractable text")
    heading = title or source_url or "Web page"
    result = f"# {heading}\n\n{body}\n".replace("\x00", "")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in result):
        result = result.encode("utf-16", errors="surrogatepass").decode(
            "utf-16", errors="replace"
        )
    return heading, result


def normalized_content_hash(markdown: str) -> str:
    normalized = markdown.replace("\r\n", "\n").strip() + "\n"
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
```

This converter intentionally produces inert text and removes scripts/styles. Link discovery must parse the original HTML separately before it is discarded. A future readability extractor may replace the body extraction behind the same return contract.

### 17.4 Public-destination authorization and DNS-pinned connection

Target: `src/connectors/url/fetcher.py`

Derived from `authorize_destination` and `_open_validated_connection` in the supplied `crawl_proxy.py`. The old proxy token is removed; the immutable `CrawlSpec` is now the authority. HTTPS adds `server_hostname=host` so certificate validation still checks the requested hostname while the socket connects to an already validated address.

```python
from __future__ import annotations

import asyncio
import ssl
from typing import Iterable
from urllib.parse import urlsplit

from .policy import (
    CrawlPolicyError,
    CrawlSpec,
    host_matches,
    normalize_host,
    normalize_url,
    resolve_public_addresses,
)


def authorize_destination(
    *,
    spec: CrawlSpec,
    host: str,
    port: int,
) -> tuple[str, ...]:
    normalized_host = normalize_host(host)
    if port not in {80, 443}:
        raise CrawlPolicyError("destination port is not permitted")
    if not host_matches(normalized_host, spec.allowed_hosts):
        raise CrawlPolicyError("destination hostname is not within this crawl scope")
    return resolve_public_addresses(normalized_host, port)


async def open_validated_connection(
    *,
    host: str,
    port: int,
    addresses: Iterable[str],
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    last_error: OSError | None = None
    tls_context = ssl.create_default_context() if port == 443 else None
    for address in addresses:
        try:
            return await asyncio.wait_for(
                asyncio.open_connection(
                    address,
                    port,
                    ssl=tls_context,
                    server_hostname=host if tls_context else None,
                ),
                timeout=10,
            )
        except OSError as exc:
            last_error = exc
    raise CrawlPolicyError("destination connection failed") from last_error


async def open_url_connection(
    value: str,
    *,
    spec: CrawlSpec,
) -> tuple[str, asyncio.StreamReader, asyncio.StreamWriter]:
    canonical = normalize_url(value)
    parsed = urlsplit(canonical)
    host = normalize_host(parsed.hostname or "")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not spec.allows_url(canonical):
        raise CrawlPolicyError("destination URL is outside this crawl scope")
    addresses = authorize_destination(spec=spec, host=host, port=port)
    reader, writer = await open_validated_connection(
        host=host,
        port=port,
        addresses=addresses,
    )
    return canonical, reader, writer
```

The completed fetcher wraps these primitives with:

- `GET` and `HEAD` only.
- `Host` header based on the hostname, not the pinned IP.
- environment proxy use disabled.
- cookies disabled.
- streamed response-body accounting and per-response cap.
- at most five manual redirects.
- `spec.allows_url` plus fresh DNS/public-address validation before every redirect.
- content-type allowlist and charset parsing.
- connect/read/total deadlines.

Do not replace this with a preflight DNS check followed by a normal hostname request; that reintroduces a DNS-rebinding window.

### 17.5 Crawler traversal and page decisions

Target: `src/connectors/url/crawler.py`

The following target shape ports the important logic from `ScopeRedirectMiddleware` and `WebSourceSpider.parse` in the supplied `crawl_runner.py`, while removing Scrapy, proxy, filesystem-manifest, and sandbox dependencies.

```python
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import time
from typing import Protocol
from urllib.parse import urljoin

from .document import html_to_markdown_document, normalized_content_hash
from .policy import CrawlSpec, normalize_url


USER_AGENT = "OpenRAGCrawler/1.0 (+https://openrag.ai/crawler; crawler@openrag.ai)"
MAX_RESPONSE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class FetchedPage:
    requested_url: str
    final_url: str
    status: int
    content_type: str
    encoding: str
    body: bytes
    links: tuple[str, ...]
    noindex: bool = False
    nofollow: bool = False


@dataclass(frozen=True)
class CrawledPage:
    canonical_url: str
    title: str
    markdown: str
    content_hash: str
    depth: int
    source_bytes: int


@dataclass
class CrawlResult:
    pages: list[CrawledPage] = field(default_factory=list)
    fetched_urls: set[str] = field(default_factory=set)
    indexed_urls: set[str] = field(default_factory=set)
    fetched_page_count: int = 0
    total_bytes: int = 0
    finish_reason: str = "complete"

    @property
    def complete(self) -> bool:
        return self.finish_reason == "complete"


class SafeFetcher(Protocol):
    async def fetch(self, url: str, *, spec: CrawlSpec) -> FetchedPage: ...


class RobotsPolicy(Protocol):
    async def can_fetch(self, url: str, *, user_agent: str, spec: CrawlSpec) -> bool: ...


async def crawl(
    spec: CrawlSpec,
    *,
    fetcher: SafeFetcher,
    robots: RobotsPolicy,
) -> CrawlResult:
    started = time.monotonic()
    result = CrawlResult()
    frontier: deque[tuple[str, int]] = deque([(spec.seed_url, 0)])
    queued = {normalize_url(spec.seed_url)}

    while frontier:
        if time.monotonic() - started >= spec.timeout_seconds:
            result.finish_reason = "max_time"
            break
        if result.fetched_page_count >= spec.max_pages:
            result.finish_reason = "max_pages"
            break

        requested_url, depth = frontier.popleft()
        canonical_request = normalize_url(requested_url)
        if canonical_request in result.fetched_urls or not spec.allows_url(canonical_request):
            continue
        if not await robots.can_fetch(canonical_request, user_agent=USER_AGENT, spec=spec):
            result.fetched_urls.add(canonical_request)
            continue

        response = await fetcher.fetch(canonical_request, spec=spec)
        final_url = normalize_url(response.final_url)
        if not spec.allows_url(final_url):
            # Fetcher should already reject this; retain a second boundary here.
            raise ValueError("redirect target is outside the URL source scope")
        result.fetched_page_count += 1
        result.fetched_urls.add(canonical_request)
        result.fetched_urls.add(final_url)

        content_type = response.content_type.lower().split(";", 1)[0]
        if content_type not in {"text/html", "application/xhtml+xml", "application/xml", "text/xml"}:
            continue

        if not response.noindex and final_url not in result.indexed_urls:
            title, markdown = html_to_markdown_document(
                response.body,
                encoding=response.encoding,
                source_url=final_url,
            )
            charged_bytes = max(len(response.body), len(markdown.encode("utf-8")))
            if result.total_bytes + charged_bytes > spec.max_total_bytes:
                result.finish_reason = "max_total_bytes"
                break
            result.total_bytes += charged_bytes
            result.indexed_urls.add(final_url)
            result.pages.append(
                CrawledPage(
                    canonical_url=final_url,
                    title=title,
                    markdown=markdown,
                    content_hash=normalized_content_hash(markdown),
                    depth=depth,
                    source_bytes=len(response.body),
                )
            )

        if response.nofollow or depth >= spec.max_depth:
            continue
        for href in response.links:
            target = normalize_url(urljoin(final_url, href))
            if target in queued or target in result.fetched_urls:
                continue
            if spec.allows_url(target):
                queued.add(target)
                frontier.append((target, depth + 1))

    return result
```

Implementation requirements that must remain around this seed:

- A capped result is intentionally `complete=False`, which prevents missing-page deletion.
- A disabled page may still be fetched and traversed, but its `CrawledPage` must be filtered before ingestion.
- `robots.txt` is fetched through the same safe transport and cached per host for the run.

### 17.6 Service and task orchestration patterns

Targets: `src/connectors/url/service.py` and `src/connectors/url/processor.py`

The supplied `application.py` contains useful validation, ownership, active-run, and safe-error patterns. The self-contained OpenRAG adaptation is:

```python
from __future__ import annotations

from typing import Any

from .policy import CrawlPolicyError, CrawlSpec


def validate_source_name(value: str) -> str:
    name = value.strip()
    if not name or len(name) > 200:
        raise ValueError("URL source name must be between 1 and 200 characters")
    return name


def safe_crawl_error(exc: Exception) -> str:
    if isinstance(exc, (CrawlPolicyError, PermissionError, FileNotFoundError, ValueError)):
        return str(exc)[:300]
    return f"{type(exc).__name__}: crawl failed"


async def create_source_and_start(
    *,
    repo: Any,
    task_service: Any,
    projection_writer: Any,
    actor: Any,
    name: str,
    spec_data: dict[str, Any],
    resync_behavior: str,
    removed_page_behavior: str,
) -> tuple[Any, str]:
    """Transaction/service outline; concrete types come from OpenRAG."""
    title = validate_source_name(name)
    spec = CrawlSpec.from_dict(spec_data)
    source = await repo.create_source(
        owner_user_id=actor.user_id,
        name=title,
        crawl_spec=spec.to_dict(),
        resync_behavior=resync_behavior,
        removed_page_behavior=removed_page_behavior,
        status="processing",
    )
    await projection_writer.upsert_source(source)
    task_id = await task_service.create_website_source_task(
        owner_user_id=actor.user_id,
        source_id=source.id,
        source_name=source.name,
        jwt_token=actor.jwt_token,
    )
    await repo.attach_task(source.id, task_id)
    return source, task_id


async def start_source_sync(
    *,
    repo: Any,
    task_service: Any,
    actor: Any,
    source_id: str,
) -> str:
    source = await repo.get_owned_source(source_id, actor.user_id)
    if source is None:
        raise FileNotFoundError("URL source not found")
    # Repository implementation must make this check-and-create atomic.
    if await repo.has_active_run(source_id):
        raise RuntimeError("a crawl is already running for this URL source")
    run = await repo.create_run(
        source_id=source_id,
        settings_snapshot=source.crawl_spec,
        status="accepted",
    )
    task_id = await task_service.create_website_source_task(
        owner_user_id=actor.user_id,
        source_id=source.id,
        source_name=source.name,
        crawl_run_id=run.id,
        jwt_token=actor.jwt_token,
    )
    await repo.attach_run_task(run.id, task_id)
    return task_id
```

This replaces the supplied code's `ThreadPoolExecutor` and `_jobs` map with OpenRAG's task system and persisted crawl runs. The route must commit source/run state before scheduling work so the task never references an invisible row.

The processor's page decision should remain a pure helper:

```python
from enum import StrEnum


class PageIngestDecision(StrEnum):
    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    SUPPRESSED = "suppressed"


def page_ingest_decision(existing_page: Any | None, new_hash: str) -> PageIngestDecision:
    if existing_page is None:
        return PageIngestDecision.NEW
    if existing_page.suppressed_by_user:
        return PageIngestDecision.SUPPRESSED
    if existing_page.content_hash == new_hash:
        return PageIngestDecision.UNCHANGED
    return PageIngestDecision.CHANGED
```

### 17.7 Narrow runtime interfaces

Targets: `src/connectors/url/ports.py` or colocated protocols.

The supplied `ports.py` correctly keeps orchestration dependent on a narrow role interface. Because this deployment does not use `CrawlerSandbox`, retain the pattern with URL-specific roles:

```python
from __future__ import annotations

from typing import Protocol

from .crawler import CrawlResult, FetchedPage
from .policy import CrawlSpec


class SafeFetcher(Protocol):
    async def fetch(self, url: str, *, spec: CrawlSpec) -> FetchedPage: ...


class WebsiteCrawler(Protocol):
    async def crawl(self, spec: CrawlSpec) -> CrawlResult: ...


class SourceProjectionWriter(Protocol):
    async def upsert_source(self, source: object) -> None: ...
    async def delete_source(self, source_id: str) -> None: ...
```

Inject these roles into the service/processor. Tests can provide fakes, and a future isolated runtime can implement `WebsiteCrawler` without changing source/page business logic.

### 17.8 Frontend form state and payload conversion

Target: `frontend/components/connectors/url/url-form-state.ts`

Derived from the supplied `WebSourcesFeature.tsx`. PII and source-list concerns are removed, page scope uses depth `0`, and the re-sync choices requested for OpenRAG are included.

```typescript
export type UrlCrawlScope = "page" | "path" | "site";
export type UrlResyncBehavior = "full" | "root_only";
export type UrlRemovedPageBehavior = "retain" | "delete";

export interface UrlSourceFormState {
  name: string;
  url: string;
  scope: UrlCrawlScope;
  allowSubdomains: boolean;
  additionalHosts: string;
  includePaths: string;
  excludePaths: string;
  maximumPages: string;
  maximumDepth: string;
  maximumDownloadedMb: string;
  maximumCrawlMinutes: string;
  resyncBehavior: UrlResyncBehavior;
  removedPageBehavior: UrlRemovedPageBehavior;
}

export interface CreateUrlSourcePayload {
  name: string;
  crawl_spec: {
    seed_url: string;
    scope: UrlCrawlScope;
    allowed_hosts: string[];
    include_path_prefixes: string[];
    exclude_path_prefixes: string[];
    max_pages: number;
    max_depth: number;
    max_total_bytes: number;
    timeout_seconds: number;
  };
  resync_behavior: UrlResyncBehavior;
  removed_page_behavior: UrlRemovedPageBehavior;
  change_detection: "normalized_content_hash";
}

export function emptyUrlSourceForm(): UrlSourceFormState {
  return {
    name: "",
    url: "",
    scope: "path",
    allowSubdomains: false,
    additionalHosts: "",
    includePaths: "",
    excludePaths: "",
    maximumPages: "250",
    maximumDepth: "4",
    maximumDownloadedMb: "128",
    maximumCrawlMinutes: "15",
    resyncBehavior: "full",
    removedPageBehavior: "retain",
  };
}

export function linesToValues(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function urlSourcePayloadFromForm(
  form: UrlSourceFormState,
): CreateUrlSourcePayload {
  const parsed = new URL(form.url);
  const seedHost = parsed.hostname.toLowerCase();
  const seedPath = parsed.pathname || "/";
  const requestedPaths = linesToValues(form.includePaths);
  const includePaths =
    form.scope === "site"
      ? ["/"]
      : form.scope === "page"
        ? [seedPath]
        : requestedPaths.length
          ? requestedPaths
          : [seedPath];

  const allowedHosts = [seedHost];
  if (form.allowSubdomains) allowedHosts.push(`*.${seedHost}`);
  allowedHosts.push(...linesToValues(form.additionalHosts));

  return {
    name: form.name.trim(),
    crawl_spec: {
      seed_url: form.url.trim(),
      scope: form.scope,
      allowed_hosts: Array.from(new Set(allowedHosts)),
      include_path_prefixes: includePaths,
      exclude_path_prefixes: linesToValues(form.excludePaths),
      max_pages: form.scope === "page" ? 1 : Number(form.maximumPages),
      max_depth: form.scope === "page" ? 0 : Number(form.maximumDepth),
      max_total_bytes: Number(form.maximumDownloadedMb) * 1024 * 1024,
      timeout_seconds: Number(form.maximumCrawlMinutes) * 60,
    },
    resync_behavior: form.resyncBehavior,
    removed_page_behavior: form.removedPageBehavior,
    change_detection: "normalized_content_hash",
  };
}

export interface UrlSourceFormErrors {
  name?: string;
  url?: string;
  additionalHosts?: string;
  includePaths?: string;
  excludePaths?: string;
  maximumPages?: string;
  maximumDepth?: string;
  maximumDownloadedMb?: string;
  maximumCrawlMinutes?: string;
}

export function validateUrlSourceForm(
  form: UrlSourceFormState,
): UrlSourceFormErrors {
  const errors: UrlSourceFormErrors = {};
  if (!form.name.trim()) errors.name = "Connection name is required";
  try {
    const parsed = new URL(form.url);
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      errors.url = "Starting URL must use HTTP or HTTPS";
    }
    if (parsed.username || parsed.password) {
      errors.url = "Starting URL cannot include credentials";
    }
  } catch {
    errors.url = "Enter a valid starting URL";
  }
  for (const path of linesToValues(form.includePaths)) {
    if (!path.startsWith('/')) errors.includePaths = "Include paths must begin with /";
  }
  for (const path of linesToValues(form.excludePaths)) {
    if (!path.startsWith('/')) errors.excludePaths = "Exclude paths must begin with /";
  }
  for (const host of linesToValues(form.additionalHosts)) {
    if (host.includes('://') || host.includes('/') || host.startsWith('*.')) {
      errors.additionalHosts = "Enter exact hostnames, one per line";
    }
  }
  const positive = (
    key: keyof UrlSourceFormErrors,
    value: string,
    label: string,
    minimum = 1,
  ) => {
    const number = Number(value);
    if (!Number.isInteger(number) || number < minimum) {
      errors[key] = `${label} must be ${minimum} or greater`;
    }
  };
  if (form.scope !== "page") {
    positive("maximumPages", form.maximumPages, "Maximum pages");
    positive("maximumDepth", form.maximumDepth, "Maximum depth", 0);
  }
  positive("maximumDownloadedMb", form.maximumDownloadedMb, "Maximum downloaded MB");
  positive("maximumCrawlMinutes", form.maximumCrawlMinutes, "Maximum crawl minutes");
  return errors;
}
```

The modal consumes these pure functions but uses OpenRAG's existing `Dialog`, `Button`, `Input`, `Textarea`, `Switch`, and `Collapsible` components. Do not copy the supplied component's `orn-*` classes or its source-list/polling UI.

### 17.9 Existing OpenRAG native-ingestion call site to extend

Target: `src/models/processors.py`

The reusable OpenRAG section is the current native pipeline, not the supplied product's upload service. Preserve the existing body of `process_document_standard`; extend only its identity/context boundary as follows:

```python
async def process_document_standard(
    self,
    file_path: str,
    file_hash: str,
    # Existing parameters remain unchanged...
    document_id: str | None = None,
    source_url: str | None = None,
    record_kind: str | None = None,
    web_source_id: str | None = None,
    web_page_id: str | None = None,
    root_source_url: str | None = None,
    replace_existing: bool = False,
):
    resolved_document_id = document_id or file_hash

    if not replace_existing and await self.check_document_exists(
        resolved_document_id,
        opensearch_client,
    ):
        return {"status": "unchanged", "id": resolved_document_id}

    # Keep the existing text/docling conversion, chunking, embeddings, ACL,
    # stale-chunk deletion, and error handling. Change stale deletion and chunk
    # IDs to use resolved_document_id, then construct the existing context with:
    index_context = DocumentIndexContext(
        document_id=resolved_document_id,
        filename=filename,
        mimetype=slim_doc["mimetype"],
        embedding_model=embedding_model,
        embedding_provider=embedding_provider,
        owner=owner,
        owner_name=owner_name,
        owner_email=owner_email,
        file_size=file_size,
        connector_type=connector_type,
        source_url=source_url,
        record_kind=record_kind,
        web_source_id=web_source_id,
        web_page_id=web_page_id,
        root_source_url=root_source_url,
        allowed_users=allowed_users,
        allowed_groups=allowed_groups,
        allowed_principals=allowed_principals,
        allowed_principal_labels=allowed_principal_labels,
        is_sample_data=is_sample_data,
    )

    index_chunks = [
        DocumentIndexChunk(
            chunk_id=f"{resolved_document_id}_{index}",
            text=chunk["text"],
            vector=vector,
            page=chunk["page"],
            metadata=chunk_metadata,
        )
        for index, (chunk, vector) in enumerate(
            zip(slim_doc["chunks"], embeddings, strict=True)
        )
    ]
```

This snippet is a signature/body delta, not a replacement for the existing method. The implementation must retain all current provider, token splitting, ACL, parser, stale-chunk, and writer logic around it.

## 18. Test file plan

Backend additions:

- `tests/unit/test_url_crawl_policy.py`: normalization, scope, ports, host rules, private/mixed DNS, query policy.
- `tests/unit/test_url_safe_fetcher.py`: pinned resolution, TLS hostname preservation, redirects, no proxy environment, byte/time caps.
- `tests/unit/test_url_crawler.py`: depth/frontier dedupe, robots, noindex/nofollow, completion versus capped results.
- `tests/unit/test_url_document.py`: inert conversion, stable normalization, content hashes.
- `tests/unit/test_url_source_processor.py`: stable IDs, unchanged skip, replacement, suppression, reconciliation matrix.
- `tests/unit/test_url_source_repository.py`: ownership, unique canonical page, cascade, active-run guard, child pagination.
- `tests/unit/test_url_projection.py`: projection fields, DLS ownership, child-count/status updates, deletion.
- Extend document writer/processor tests for the optional stable document ID and new top-level fields.
- Extend connector discovery/access/auth tests for `managed` and `always_connected`.
- Extend file/search service tests for hidden web-page records and root search collapse.
- Extend Sync All tests for URL source tasks plus partial connector errors.
- `tests/integration/core/test_url_connector.py`: create → processing parent → children → chunks, root/child sync-delete behavior, and RBAC isolation.
- Migration upgrade/downgrade coverage for `0008_website_sources.py`.

Frontend additions, colocated as required by the repository:

- `url-form-state.test.ts`: defaults, scope conversion, path parsing, caps.
- `url-source-dialog.test.tsx`: two steps, validation, advanced controls, notices, request payload, task registration.
- Connector registry/query/card/dropdown tests: always-connected Settings card and URL modal entry points.
- `knowledge-data-table.test.tsx`: only behavior jsdom can observe; AG Grid geometry stays in Playwright.
- `use-knowledge-pagination.test.ts`: reset and cursor behavior extracted from the page.
- `website-parent-cell.test.tsx`: icon, child badge, tooltip, navigation.
- `website-children-view.test.tsx`: backend search/sort/page request, header layout, child-to-chunks navigation, disabled state.
- `website-actions-dropdown.test.tsx`: text-only root/child actions and confirmations.
- Extend chunks tests for document-ID queries and contextual Back.
- Add Playwright cases under `frontend/tests/` for modal focus/step interaction, AG Grid layout, root → children → chunks, and destructive flows.

Frontend tests must use `renderWithProviders` and per-test MSW handlers. They must not mock modules under `app/api/queries` or `app/api/mutations`, and new executable lines must satisfy the 80% diff-coverage gate.

## 19. Delivery sequence

1. Add managed connector capabilities and regression tests without exposing URL yet.
2. Add source/page/run schema, repository, and migration.
3. Port and harden policy, safe fetcher, robots, crawl, and normalized document conversion with unit tests.
4. Add stable document identity and URL metadata to the native processor/writer and OpenSearch mappings.
5. Add URL service, processor, parent projection, API routes, and task wrappers.
6. Add root Knowledge listing/search projection behavior, child API search/pagination, chunks document-ID lookup, and Sync All integration.
7. Extract the Knowledge table, header, toolbar, column hook, pagination hook, and pure state helpers; prove the existing page remains unchanged with tests.
8. Register URL in frontend discovery, Settings, and Add Knowledge.
9. Add the two-step modal and immediate processing parent behavior.
10. Add parent cell/actions and the scoped child view using the extracted Knowledge components.
11. Complete OSS/IBM verification, RBAC/DLS tests, migration tests, diff coverage, and Playwright geometry/navigation coverage.

Each step should be independently reviewable. In particular, the Knowledge refactor should land with no URL behavior in the same commit, making regressions distinguishable from feature changes.

## 20. Acceptance criteria

- URL is an always-connected built-in connector in both OSS and IBM modes.
- Add Knowledge → URL opens the two-step modal shown in the supplied reference structure.
- URL ingestion never uses Langflow.
- Submitting returns to Knowledge and immediately shows a processing parent row.
- A root source appears once at the top level with the established URL icon and a child-count badge.
- Clicking the root opens a scoped Knowledge-style child table.
- Every canonical crawled page appears once as an individual child document.
- Clicking a child opens its chunks.
- Parent Sync/Delete work from both the main table and child view.
- Parent deletion removes all children and chunks.
- Child deletion leaves a disabled visible row and removes its chunks.
- Root sync skips manually disabled children.
- Manual child re-sync re-enables and ingests it.
- Full/root-only and retained/deleted-page settings behave exactly as saved.
- Repeated canonical URLs and unchanged content are not re-ingested.
- Cross-domain traversal, private destinations, unsafe redirects, and safety-cap bypasses are rejected.
- The feature follows existing Knowledge behavior, design tokens, accessibility, RBAC, and test conventions.
