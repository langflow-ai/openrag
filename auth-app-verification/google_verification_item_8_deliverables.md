# Google Verification Item 8 Deliverables: Protect Ingested Drive Data

Item 8 is:

> Protect ingested Drive data.

The goal is to show that Google Drive files ingested through the OpenRAG connector are only visible to authorized OpenRAG users and tenants. Because `drive.readonly` can allow broad read access to Drive files, the important verification evidence is not source code by itself. The important evidence is that OpenRAG stores authorization metadata with every indexed Drive-derived object and enforces that metadata during search, retrieval, and chat.

---

## Summary of required deliverables

- [ ] Metadata mapping.
- [ ] OpenSearch index mapping update if needed.
- [ ] Retrieval authorization filter.
- [ ] Tests proving user A cannot retrieve user B's Drive-ingested content.
- [ ] Tests for tenant isolation.

---

## 1. Metadata mapping

### What to produce

Create a short metadata mapping document or table that shows which authorization fields are attached to every Drive-derived document, chunk, embedding, and OpenSearch record.

At minimum, every indexed Drive-derived item should include:

```text
owner_user_id
tenant_id
connector_id
source_type = google_drive
source_document_id = <google_drive_file_id>
source_document_name
source_modified_at
```

### Recommended mapping table

| Field | Source | Purpose | Required |
|---|---|---|---:|
| `owner_user_id` | OpenRAG authenticated user | Identifies the user who connected Drive or owns the connection | Yes |
| `tenant_id` | OpenRAG tenant/org context | Enforces tenant isolation | Yes |
| `connector_id` | OpenRAG connector account model | Ties records to a specific Google Drive connection | Yes |
| `source_type` | Connector type | Identifies records as Google Drive-derived data | Yes |
| `source_document_id` | Google Drive file ID | Supports dedupe, sync, reconcile, deletion, and source attribution | Yes |
| `source_document_name` | Google Drive file metadata | Supports user-facing source display and support diagnostics | Yes |
| `source_modified_at` | Google Drive file metadata | Supports sync/reconcile freshness checks | Yes |
| `allowed_user_ids` / ACL fields | OpenRAG permissions model, if used | Supports per-user retrieval filtering | If applicable |
| `allowed_group_ids` / ACL fields | OpenRAG permissions model, if used | Supports group-based retrieval filtering | If applicable |

### Acceptance criteria

- Every indexed Drive document has `tenant_id`, `connector_id`, `source_type`, and source document metadata.
- Every indexed Drive chunk or embedding can be traced back to the owning user, tenant, connector, and Drive file.
- The mapping explains whether access is enforced by owner, tenant, explicit ACLs, connector visibility rules, or a combination.
- The mapping supports deletion of all indexed records for a disconnected connector or deleted Drive file.

---

## 2. OpenSearch index mapping update if needed

### What to produce

Provide the OpenSearch mapping or schema evidence showing that authorization and source fields are indexed or stored in a way retrieval filters can use.

If the current index already supports these fields, this deliverable can be a short note saying no mapping migration is required, with evidence from the current index mapping.

### Fields to verify

| Field | Expected behavior |
|---|---|
| `tenant_id` | Filterable exact-match field |
| `owner_user_id` | Filterable exact-match field, if owner filtering is used |
| `connector_id` | Filterable exact-match field |
| `source_type` | Filterable exact-match field, value is `google_drive` |
| `source_document_id` | Filterable exact-match field |
| ACL fields | Filterable exact-match or terms-query compatible fields, if ACLs are used |
| `source_document_name` | Stored for attribution/display; may also be searchable if useful |
| `source_modified_at` | Date field if used for sync/reconcile logic |

### Acceptance criteria

- Retrieval can filter Drive-derived content by `tenant_id`.
- Retrieval can filter by owner, ACL, connector visibility, or the selected OpenRAG authorization model.
- Drive-derived records can be deleted or reconciled by `connector_id` and `source_document_id`.
- The mapping avoids relying only on user-visible text fields for authorization decisions.

---

## 3. Retrieval authorization filter

### What to produce

Provide a short technical explanation of the filter applied to every search/chat retrieval query that can return Google Drive-derived content.

The required retrieval rule is:

```text
tenant_id
AND allowed user/group/ACL
AND connector visibility rules
```

### Example reviewer-facing explanation

```text
When an OpenRAG user searches or chats over indexed knowledge, OpenRAG applies authorization filters before returning Drive-derived content. Google Drive records are tagged with tenant, connector, source, owner, and source document metadata at ingestion time. Retrieval queries are constrained to the user's tenant and to records the user is allowed to access through OpenRAG user, group, ACL, or connector visibility rules. As a result, one user cannot retrieve another user's Drive-ingested content unless OpenRAG authorization explicitly grants that access.
```

### Acceptance criteria

- The filter is applied to search retrieval and chat/RAG retrieval.
- The filter is applied server-side and cannot be bypassed by the client.
- The filter includes tenant isolation.
- The filter includes user, group, ACL, or connector visibility rules.
- The filter applies to Drive-derived chunks, embeddings, and source document records.

---

## 4. Tests proving user A cannot retrieve user B's Drive-ingested content

### What to produce

Create or provide automated test evidence for cross-user isolation within the same tenant or authorization boundary.

### Minimum test scenario

```text
1. Create user A and user B.
2. Connect or simulate a Google Drive connector for user A.
3. Ingest a unique Drive document for user A.
4. Authenticate as user B.
5. Search or ask a chat question using terms that should match user A's Drive document.
6. Assert that user B receives no chunks, sources, answers, or citations from user A's Drive document.
7. Authenticate as user A.
8. Run the same query.
9. Assert that user A can retrieve the expected Drive document.
```

### Acceptance criteria

- User B cannot retrieve user A's Drive-ingested chunks.
- User B cannot see source attribution for user A's Drive files.
- User B cannot infer document presence from retrieval metadata, citations, or counts.
- User A can still retrieve their own authorized Drive content.
- The test covers the same retrieval path used by production search/chat, not only a helper function.

---

## 5. Tests for tenant isolation

### What to produce

Create or provide automated test evidence that Drive-ingested content cannot cross tenant or organization boundaries.

### Minimum test scenario

```text
1. Create tenant A and tenant B.
2. Create a user in tenant A and a user in tenant B.
3. Ingest a unique Google Drive document under tenant A.
4. Authenticate as the tenant B user.
5. Search or ask a chat question using terms from tenant A's Drive document.
6. Assert that tenant B receives no chunks, sources, answers, or citations from tenant A.
7. Authenticate as the tenant A user.
8. Run the same query.
9. Assert that tenant A can retrieve the expected Drive document.
```

### Acceptance criteria

- Tenant B cannot retrieve tenant A's Drive-ingested chunks.
- Tenant B cannot see tenant A source attribution or document metadata.
- Tenant filtering is mandatory for retrieval queries.
- Tests cover indexed document retrieval, not only database row access.
- Tests include Google Drive-derived records specifically, identified by `source_type = google_drive`.

---

## What to provide to Google

For Google verification or a restricted-scope review, provide evidence rather than internal implementation detail unless requested.

### Deliverable 1: Metadata mapping

Provide this table to show that Drive-derived data is tagged with authorization and source metadata before it is stored or indexed.

| Metadata field | Applied to | Purpose |
|---|---|---|
| `tenant_id` | Documents, chunks, embeddings, index records | Prevents data from crossing tenant/org boundaries |
| `owner_user_id` | Documents, chunks, embeddings, index records | Links Drive-ingested content to the OpenRAG user who owns or created the connector |
| `connector_id` | Documents, chunks, embeddings, index records | Links indexed content to the specific Google Drive connector connection |
| `source_type` | Documents, chunks, embeddings, index records | Identifies records as Google Drive-derived data using `google_drive` |
| `source_document_id` | Documents, chunks, embeddings, index records | Stores the Google Drive file ID for sync, reconcile, attribution, and deletion |
| `source_document_name` | Documents and source attribution records | Displays the source file name to authorized users |
| `source_modified_at` | Documents and sync metadata | Supports freshness checks and sync/reconcile behavior |
| ACL/user/group fields, if enabled | Chunks and index records used for retrieval | Restricts retrieval to authorized users or groups |

Google-facing statement:

```text
OpenRAG tags every Google Drive-derived document, chunk, embedding, and index record with tenant, owner, connector, source type, and source document metadata. These fields allow OpenRAG to enforce access controls during retrieval and to delete or reconcile Drive-derived data when a connector is disconnected or a Drive file changes.
```

Evidence to attach:

- Metadata/schema table.
- Example sanitized indexed record showing the authorization fields.
- Short note explaining whether access is enforced by owner, group/ACL, connector visibility, or a combination.

### Deliverable 2: Index mapping evidence

Provide evidence that authorization fields are filterable in the search index.

| Field | Required index behavior |
|---|---|
| `tenant_id` | Exact-match filterable |
| `owner_user_id` | Exact-match filterable if owner filtering is used |
| `connector_id` | Exact-match filterable |
| `source_type` | Exact-match filterable |
| `source_document_id` | Exact-match filterable |
| ACL/user/group fields | Terms-query compatible if ACL filtering is used |
| `source_modified_at` | Date field if used by sync or reconcile logic |

Google-facing statement:

```text
OpenRAG stores authorization metadata in filterable index fields. Retrieval queries do not rely on document text to determine authorization. Instead, server-side filters constrain candidate results by tenant and by the user's OpenRAG permissions before Drive-derived chunks or citations can be returned.
```

Evidence to attach:

- OpenSearch mapping export or schema excerpt.
- If no migration was needed, a short note explaining that the existing mapping already supports the required filter fields.
- Optional sanitized example query showing authorization filters applied.

### Deliverable 3: Retrieval authorization filter summary

Provide a concise explanation of the server-side authorization filter used by search and chat retrieval.

Required rule:

```text
tenant_id
AND allowed user/group/ACL
AND connector visibility rules
```

Google-facing statement:

```text
When an OpenRAG user searches or chats over indexed knowledge, OpenRAG applies server-side authorization filters before returning Google Drive-derived content. Retrieval is constrained to the user's tenant and to records the user is allowed to access through OpenRAG permissions, groups, ACLs, or connector visibility rules. Client requests cannot bypass these filters.
```

Evidence to attach:

- Short architecture note showing where the retrieval filter is applied.
- Sanitized query/filter example.
- Screenshot or log excerpt showing a retrieval request constrained by tenant and authorization metadata.

### Deliverable 4: Cross-user isolation test evidence

Provide evidence that one user cannot retrieve another user's Google Drive-ingested content.

Recommended test summary:

| Test case | Expected result |
|---|---|
| User A ingests a unique Drive document | The document is indexed with user A's authorization metadata |
| User B searches for exact terms from user A's document | No chunks, citations, source metadata, or answer content from user A's document are returned |
| User A searches for the same terms | User A can retrieve the expected Drive document |

Google-facing statement:

```text
OpenRAG includes automated tests proving that user B cannot retrieve user A's Google Drive-ingested content. The tests use the production retrieval path and verify that unauthorized users receive no chunks, citations, source metadata, or answer content from another user's Drive document.
```

Evidence to attach:

- Test name or test file path.
- CI output or local test output.
- Screenshots or summarized results showing user B gets no Drive-derived result while user A can retrieve the document.

### Deliverable 5: Tenant isolation test evidence

Provide evidence that Google Drive-ingested content cannot cross tenant or organization boundaries.

Recommended test summary:

| Test case | Expected result |
|---|---|
| Tenant A ingests a unique Drive document | The document is indexed with tenant A metadata |
| Tenant B searches for exact terms from tenant A's document | No chunks, citations, source metadata, or answer content from tenant A are returned |
| Tenant A searches for the same terms | Tenant A can retrieve the expected Drive document |

Google-facing statement:

```text
OpenRAG includes automated tests proving that Google Drive-derived records are isolated by tenant. A user in tenant B cannot retrieve chunks, citations, source metadata, or answer content from tenant A's Drive-ingested documents. Tenant filtering is enforced server-side for search and chat retrieval.
```

Evidence to attach:

- Test name or test file path.
- CI output or local test output.
- Sanitized test fixtures showing separate tenant IDs.
- Screenshots or summarized results showing tenant B gets no Drive-derived result while tenant A can retrieve the document.

### Submission checklist

- [ ] Metadata mapping table prepared.
- [ ] Sanitized indexed-record example prepared.
- [ ] OpenSearch mapping or schema excerpt prepared.
- [ ] Retrieval authorization filter explanation prepared.
- [ ] Cross-user isolation test evidence prepared.
- [ ] Tenant isolation test evidence prepared.
- [ ] Final Google-facing statement included in the verification package.

---

## Suggested final statement

Use a statement like this in the verification package:

```text
OpenRAG protects Google Drive-derived data by tagging every ingested document, chunk, embedding, and index record with authorization metadata including tenant, connector, source type, source document ID, and owner or ACL information. Search and chat retrieval apply server-side authorization filters that restrict results by tenant and by the user's OpenRAG permissions or connector visibility rules. Automated tests verify that one user cannot retrieve another user's Drive-ingested content and that Drive-derived data cannot cross tenant boundaries.
```
