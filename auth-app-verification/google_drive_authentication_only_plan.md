# Project Plan: Google Drive Authentication Only

This plan assumes:

- OpenRAG users already authenticate through the existing OpenRAG auth system.
- Google OAuth is used only to connect a user’s Google Drive account.
- The connector uses:

```text
https://www.googleapis.com/auth/drive.readonly
```

Google defines `drive.readonly` as permission to “view and download all your Drive files,” and Drive restricted scopes require restricted-scope verification; if restricted-scope data is stored or transmitted through servers, a security assessment is required.

---

## 1. Define the release boundary

**Goal:** Make it very clear that this release is not “Sign in with Google.”

The product story should be:

> OpenRAG users authenticate using the existing OpenRAG authentication system. After login, a user may connect Google Drive as a read-only document source. Google OAuth is used only to authorize OpenRAG to read Drive files for ingestion, indexing, synchronization, and retrieval.

### In scope

| Item | Included |
|---|---|
| Google Drive OAuth authorization | Yes |
| `drive.readonly` scope | Yes |
| Refresh-token support | Yes |
| Google Drive connect/disconnect | Yes |
| Drive file/folder listing or sync | Yes |
| Ingestion from Drive | Yes |
| Store indexed Drive-derived content | Yes |
| Revoke/delete connector data | Yes |

### Out of scope

| Item | Deferred |
|---|---|
| Sign in to OpenRAG with Google | Yes |
| Google as primary OpenRAG identity provider | Yes |
| Mapping Google login session to OpenRAG session | Yes |
| Google profile-based app login | Yes |

---

## 2. Finalize the OAuth scope strategy

**Goal:** Use only the scopes required for the connector.

### Minimum connector scope

```text
https://www.googleapis.com/auth/drive.readonly
```

This gives read-only access to view and download Drive files.

### Optional identity scopes

Add these only if OpenRAG needs to display or persist the connected Google account identity:

```text
openid
email
profile
```

For example:

> Connected as user@example.com

If you do not need that display/identity mapping, avoid these initially. Google recommends choosing the most narrowly focused scope possible and avoiding scopes the app does not require.

### Deliverables

- [X] Scope list.
- [X] Scope justification.
- [X] Decision record explaining why `drive.file` is insufficient.
- [X] Explicit statement that Google OAuth is for connector authorization only.

---

## 3. Create a production Google Cloud project

**Goal:** Separate production verification from development/testing.

### Tasks

| Task | Notes |
|---|---|
| Create dedicated production Google Cloud project | Avoid using test project |
| Enable Google Drive API | Required for connector |
| Configure OAuth consent screen | Required for OAuth |
| Create Web Application OAuth client | For OpenRAG backend/frontend OAuth callback |
| Add authorized redirect URIs | Production HTTPS callback URLs only |
| Add authorized JavaScript origins | If frontend initiates OAuth |
| Verify authorized domains | App domain, **homepage domain, privacy policy domain** |
| Remove unused test OAuth clients | Keep production project clean |

Google notes that OAuth consent configuration defines what users and reviewers see, and external apps must declare scopes.

### Deliverables

- [X] Production Google Cloud project.
- [X] Production OAuth client ID.
- [X] Production OAuth client secret.
- [X] Final redirect URI list.
- [2/3] Verified authorized domains.

---

## 4. Configure OAuth consent screen for connector-only use

**Goal:** The consent screen should not imply Google login.

### Recommended app wording

Use wording like:

> OpenRAG Google Drive Connector

or:

> OpenRAG

But the app description/homepage should clearly explain:

> This Google authorization is used to connect Google Drive as a read-only document source for OpenRAG. It is not used to sign users into OpenRAG.

### Consent screen items

| Item | Requirement |
|---|---|
| App name | Production name |
| User support email | Monitored mailbox |
| Developer contact email | Monitored mailbox |
| App logo | Production logo, if used |
| Homepage URL | Public page explaining OpenRAG and Drive connector |
| Privacy policy URL | Public, accurate, complete |
| Authorized domains | Verified |
| Scopes | `drive.readonly`, plus optional identity scopes only if needed |

Apps accessing Google APIs must verify identity and intent according to Google’s API Services User Data Policy, and external apps with branded consent screen information can require brand verification.

### Deliverables

- [X] OAuth consent screen configured.
- [X] Public homepage.
- [X] Public privacy policy.
- [X] Optional terms of service page.

---

## 5. Implement connector OAuth flow

**Goal:** Build a clean Drive authorization flow owned by the OpenRAG user.

### Flow

```text
OpenRAG user logs in using existing OpenRAG auth
        ↓
User opens Connectors > Google Drive
        ↓
User clicks Connect Google Drive
        ↓
OpenRAG redirects to Google OAuth
        ↓
User grants drive.readonly
        ↓
Google redirects back to OpenRAG callback
        ↓
OpenRAG exchanges code for tokens
        ↓
OpenRAG stores encrypted refresh token
        ↓
Connector is linked to OpenRAG user_id / tenant_id
```

### Backend requirements

| Area | Requirement |
|---|---|
| OAuth grant | Authorization code flow |
| Offline sync | Use offline access to obtain refresh token |
| Token storage | Encrypt refresh token at rest |
| Token ownership | Link token to `openrag_user_id`, `tenant_id`, `connector_id` |
| Granted scopes | Store exact granted scopes |
| Token refresh | Refresh access tokens server-side |
| Token revocation | Support disconnect/revoke |
| Logs | Never log auth code, access token, refresh token, ID token |
| Errors | Handle revoked token, expired token, admin-blocked app, insufficient permissions |

### Deliverables

- [X] `/connectors/google-drive/connect` endpoint.
- [X] `/connectors/google-drive/oauth/callback` endpoint.
- [X] Secure token storage.
- [X] Token refresh service.
- [X] Disconnect/revoke endpoint.
- [X] User-facing error messages.

---

## 6. Implement connector account model

**Goal:** Treat Google identity as a connected data-source identity, not as the OpenRAG user identity.

### Suggested data model

| Field | Purpose |
|---|---|
| `connector_id` | Internal OpenRAG connector connection ID |
| `connector_type` | `google_drive` |
| `openrag_user_id` | User who owns the connection |
| `tenant_id` / `org_id` | Enterprise boundary |
| `google_account_email` | Optional display field |
| `google_subject_id` | Optional stable Google identity if using OIDC |
| `granted_scopes` | Actual scopes granted |
| `refresh_token_encrypted` | Encrypted refresh token |
| `connection_status` | connected, expired, revoked, error |
| `created_at` | Connection creation time |
| `last_sync_at` | Last successful sync |
| `last_error_code` | Support diagnostics |
| `last_error_message` | Sanitized user-facing/support message |

### Deliverables

- [X] Connector connection table/schema.
- [X] Migration script.
- [X] Token encryption/decryption service.
- [X] Connector lifecycle status model.

---

## 7. Implement Drive read/sync behavior

**Goal:** Use the Drive token only for connector functionality.

### Tasks

| Task | Notes |
|---|---|
| List Drive files/folders | Based on the connected account |
| Download readable files | Only for ingestion |
| Capture metadata | File ID, name, MIME type, modified time, web link if allowed |
| Support shared drives if required | Requires careful testing |
| Detect deleted/removed files | Needed for reconcile/orphan cleanup |
| Handle permission errors | User may lose access to files |
| Handle quotas/rate limits | Backoff and retry |
| Track sync status | For UI and support |

### Deliverables

- [X] Drive file listing.
- [X] Drive file download.
- [X] Sync job.
- [X] Reconcile job for deleted/missing Drive files.
- [X] Rate-limit handling.
- [X] Connector status UI/API.

---

## 8. Protect ingested Drive data

**Goal:** Ensure Drive documents are only visible to authorized OpenRAG users.

Every indexed document and chunk should include authorization metadata.

### Required metadata

```text
owner_user_id
tenant_id
connector_id
source_type = google_drive
source_document_id = <google_drive_file_id>
source_document_name
source_modified_at
```

### Retrieval requirement

Every search/chat retrieval query must filter by:

```text
tenant_id
AND allowed user/group/ACL
AND connector visibility rules
```

This is critical because `drive.readonly` allows broad file reading, and OpenRAG stores derived data such as extracted text, chunks, embeddings, and OpenSearch documents.

### Deliverables

- [X] Metadata mapping.
- [X] OpenSearch index mapping update if needed.
- [X] Retrieval authorization filter.
- [X] Tests proving user A cannot retrieve user B’s Drive-ingested content.
- [X] Tests for tenant isolation.

---

## 9. Update privacy policy for Drive connector only

**Goal:** Make privacy disclosures match the connector behavior.

The privacy policy should explicitly say:

| Topic | Required content |
|---|---|
| What is accessed | Google Drive files and metadata authorized by the user |
| Why it is accessed | Ingestion, indexing, search, RAG/chat |
| What is stored | File metadata, extracted text, chunks, embeddings, index records |
| What is not done | OpenRAG does not modify, delete, or write Google Drive files |
| Token storage | Refresh tokens are stored securely/encrypted |
| Retention | How long Drive-derived content is retained |
| Deletion | How users/admins delete indexed Drive data |
| Disconnect | How users revoke Drive access |
| Human access | Restricted to support/security needs |
| Model usage | Whether Drive data is sent to embedding/LLM providers |
| Training | Whether Drive data is used for model training; ideally “not used for training” |

### Deliverables

- [X] Privacy policy update.
- [X] Google Drive connector data-use section.
- [X] Limited Use statement.
- [X] Data deletion instructions.

---

## 10. Prepare restricted-scope verification package

**Goal:** Be ready for Google verification and likely security assessment.

Apps requesting restricted scopes need verification unless they qualify for an exception, and apps that access restricted data through third-party servers may need annual security assessment.

### Verification artifacts

| Artifact | Description |
|---|---|
| Scope justification | Why OpenRAG needs `drive.readonly` |
| App homepage | Public explanation of OpenRAG Drive connector |
| Privacy policy | Public and complete |
| Demo video | Shows OAuth and Drive feature |
| Test account | For reviewer if needed |
| Reviewer instructions | Step-by-step test flow |
| Data flow diagram | OAuth token + Drive file data flow |
| Security overview | Token encryption, RBAC, deletion, logging |
| Deletion workflow | User disconnect and indexed-data deletion |
| Support contact | Monitored email |

### Scope justification draft

> OpenRAG requests `https://www.googleapis.com/auth/drive.readonly` so authenticated OpenRAG users can connect Google Drive as a read-only document source. OpenRAG uses this access to list, read, download, ingest, index, synchronize, and retrieve content from Google Drive files authorized by the user. OpenRAG does not create, modify, or delete files in Google Drive. A narrower scope such as `drive.file` is insufficient for this release because OpenRAG needs to support read-only discovery and synchronization of existing Drive folders and documents selected as enterprise knowledge sources.

---

## 11. Prepare demo video for connector-only verification

**Goal:** Show only the Google Drive connector OAuth flow and scope usage.

The demo video should show the submitted application, the complete OAuth consent workflow, the OAuth consent screen with requested scopes, and how each requested scope is used in the app.

### Demo script

1. Open OpenRAG homepage.
2. Log in using existing OpenRAG authentication.
3. Navigate to **Connectors**.
4. Choose **Google Drive**.
5. Click **Connect Google Drive**.
6. Show Google OAuth consent screen.
7. Show requested `drive.readonly` permission.
8. Approve access.
9. Return to OpenRAG.
10. Show Google Drive connected status.
11. List or sync Drive files.
12. Ingest a Drive document.
13. Ask a question over the ingested document.
14. Show answer/source attribution.
15. Disconnect Google Drive.
16. Show revoke/delete indexed data path.

### Deliverables

- [ ] Unlisted YouTube or accessible video link.
- [X] Reviewer test account.
- [X] Reviewer Drive folder/files.
- [X] Written reviewer steps.

---

## 12. Prepare security assessment evidence

**Goal:** Have the evidence ready before Google asks.

Because OpenRAG processes Drive content server-side, prepare these now.

| Evidence | What to include |
|---|---|
| Architecture diagram | Browser, OpenRAG frontend/backend, Google OAuth, Drive API, ingestion workers, Docling, OpenSearch |
| Data flow diagram | OAuth token flow, file metadata flow, file content flow, indexing flow |
| Token security | Encryption, secret storage, key rotation, revocation |
| Data storage inventory | Tokens, metadata, chunks, embeddings, indexes |
| RBAC design | User/tenant/ACL filtering at retrieval |
| Logging policy | No secrets, no raw document content in logs |
| Deletion process | Disconnect, revoke token, delete chunks/index records |
| Incident response | Security contact and escalation path |
| Vulnerability management | Dependency/container scanning, patching process |
| Subprocessors | LLM/embedding providers, hosting, storage, monitoring |

### Deliverables

- [ ] Security assessment folder.
- [ ] Architecture/data-flow diagrams.
- [ ] Token handling document.
- [ ] Data deletion runbook.
- [ ] RBAC/security test evidence.

---

## 13. Submit for verification

**Goal:** Submit the production OAuth app with connector-only positioning.

### Submission checklist

| Item | Done |
|---|---|
| Production Google Cloud project created |  |
| Drive API enabled |  |
| OAuth consent screen configured |  |
| Production OAuth client created |  |
| Authorized domains verified |  |
| Homepage published |  |
| Privacy policy published |  |
| `drive.readonly` added |  |
| Scope justification written |  |
| Demo video recorded |  |
| Reviewer instructions ready |  |
| Security package ready |  |
| Support/developer emails monitored |  |

---

## 14. Production rollout

**Goal:** Release safely after approval.

### Rollout tasks

| Task | Purpose |
|---|---|
| Deploy production OAuth client ID/secret | Use verified credentials |
| Smoke test OAuth flow | Connect, callback, token exchange |
| Smoke test token refresh | Confirm sync works after access-token expiry |
| Test disconnect | Revoke token and stop sync |
| Test delete indexed data | Remove chunks/embeddings/metadata |
| Monitor OAuth errors | Revoked, invalid_grant, access_denied |
| Monitor Drive API errors | Quota, permission, rate limit |
| Monitor ingestion failures | Docling/Langflow/OpenSearch |
| Document support runbook | Troubleshooting and escalation |

### Customer/admin docs

For enterprise customers, provide:

- Production OAuth client ID.
- App name.
- Requested scope: `drive.readonly`.
- Explanation of read-only Drive access.
- Data stored by OpenRAG.
- How to disconnect/revoke.
- How to delete indexed Drive data.
- Support contact.

---

## Suggested task breakdown

| Epic | Tasks |
|---|---|
| OAuth setup | Production project, Drive API, OAuth client, consent screen |
| Connector auth | Connect endpoint, callback, token exchange, encrypted refresh token |
| Connector lifecycle | Status, reconnect, disconnect, revoke |
| Drive sync | List, download, ingest, retry, reconcile deleted files |
| Security/RBAC | Metadata tagging, retrieval filters, tenant isolation tests |
| Privacy/compliance | Privacy policy, Limited Use, data deletion docs |
| Verification | Scope justification, demo video, reviewer instructions |
| Security assessment | Architecture, data flow, token security, deletion evidence |
| Rollout | Smoke tests, monitoring, customer admin guide |

---

## Clean release statement

> Initial production verification will cover Google Drive connector authentication only. OpenRAG users will continue to authenticate through the existing OpenRAG authentication mechanism. Google OAuth will be used only to authorize read-only access to a user’s Google Drive content through `drive.readonly`, so OpenRAG can ingest, index, synchronize, and retrieve Drive documents. Google OAuth will not be used as an OpenRAG application login provider in this release.
