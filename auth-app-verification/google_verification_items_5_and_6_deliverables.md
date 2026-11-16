# What to Provide to Google for Items 5 and 6

If items **5 and 6 are already implemented**, you do **not** need to provide Google with source-code deliverables for those items.

What you need to provide Google is **evidence** that the implemented OAuth flow and connector account model behave safely and match the requested `drive.readonly` scope.

The short version:

> Google does not need your endpoint code or database schema.  
> Google needs to understand **what the app does, why it needs `drive.readonly`, how the OAuth flow works, where Drive data goes, how tokens are protected, and how users can disconnect/delete data.**

Because `drive.readonly` is a restricted scope, Google requires restricted-scope verification, and production apps using sensitive or restricted scopes must submit scope justification and a demo video.

---

## What to provide to Google for item 5: OAuth flow

Item 5 was:

> Implement connector OAuth flow.

Since it is already implemented, provide Google with **a description and demo of the OAuth flow**.

### Provide this to Google

| Deliverable | What to provide |
|---|---|
| OAuth flow description | Explain that users first log in to OpenRAG using existing auth, then separately connect Google Drive |
| OAuth consent demo | Video showing the user clicking **Connect Google Drive** and approving `drive.readonly` |
| Callback URL | The production OAuth redirect URI used by OpenRAG |
| Scope used | Only `https://www.googleapis.com/auth/drive.readonly` |
| Scope justification | Explain why OpenRAG needs read-only Drive access |
| Disconnect flow | Show or explain how users disconnect Google Drive |
| Token handling summary | Explain that refresh tokens are stored securely and not logged |
| Error handling summary | Explain handling for revoked token, denied consent, expired token, admin-blocked app |

### What the demo video should show

For item 5, your video should show:

```text
1. User logs in to OpenRAG using existing OpenRAG authentication.
2. User opens Connectors.
3. User selects Google Drive.
4. User clicks Connect Google Drive.
5. Browser redirects to Google OAuth consent screen.
6. Consent screen shows the OpenRAG app name and requested Drive permission.
7. User approves access.
8. Google redirects back to OpenRAG.
9. OpenRAG shows Google Drive as connected.
10. User can start Drive sync or ingestion.
11. User can disconnect Google Drive.
```

Important: since this is **Drive connector authentication only**, the video should make clear that Google OAuth is **not** being used to sign in to OpenRAG.

---

## What to provide to Google for item 6: connector account model

Item 6 was:

> Implement connector account model.

Since it is already implemented, provide Google with **a high-level explanation of how OpenRAG stores and protects the connected Drive account**.

### Provide this to Google

| Deliverable | What to provide |
|---|---|
| Connector ownership explanation | Explain that each Drive connection is linked to an OpenRAG user and tenant/org |
| Token storage explanation | Explain that refresh tokens are encrypted or securely stored |
| Data storage explanation | Explain what Drive metadata/content is stored after ingestion |
| Access-control explanation | Explain that indexed Drive content is only retrievable by authorized OpenRAG users |
| Data deletion explanation | Explain how Drive-derived indexed data can be deleted |
| Disconnect/revoke explanation | Explain what happens when a user disconnects Google Drive |
| Architecture/data-flow diagram | Show OAuth tokens, Drive file data, ingestion pipeline, OpenSearch/index storage |
| Security controls summary | Encryption, RBAC, no token logging, monitoring, least privilege |

---

## What Google actually wants from you

For your case, prepare these **submission artifacts**.

## 1. App identity / branding

Provide in Google Cloud Console:

| Field | What to provide |
|---|---|
| App name | `OpenRAG` or the approved production app name |
| App logo | Production logo, if available |
| User support email | Monitored support email |
| Developer contact email | Monitored owner/team email |
| Homepage URL | Public OpenRAG homepage |
| Privacy policy URL | Public privacy policy |
| Terms URL | Optional but recommended |
| Authorized domains | Verified app/homepage/privacy/callback domains |

---

## 2. Scope declaration

Declare only this scope:

```text
https://www.googleapis.com/auth/drive.readonly
```

Do **not** include these if this release is connector-only:

```text
openid
email
profile
```

Do **not** include full Drive write scope:

```text
https://www.googleapis.com/auth/drive
```

---

## 3. Scope justification

Provide a concise explanation like this:

```text
OpenRAG requests https://www.googleapis.com/auth/drive.readonly so authenticated OpenRAG users can connect Google Drive as a read-only document source. OpenRAG uses this permission to discover, read, download, ingest, index, synchronize, search, and retrieve content from Google Drive files authorized by the user.

OpenRAG does not create, modify, move, or delete files in Google Drive. Google OAuth is not used as an OpenRAG login provider in this release. A narrower scope such as drive.file is insufficient because OpenRAG needs to support read-only discovery and synchronization of existing Drive folders and documents used as enterprise knowledge sources.
```

---

## 4. Demo video

This is one of the most important deliverables.

Your video should prove:

| Requirement | What to show |
|---|---|
| Same app | The app name/branding matches the verification submission |
| OAuth flow | User clicks Connect Google Drive and reaches Google consent screen |
| Requested scope | Consent screen shows the Drive read-only permission |
| Scope usage | User syncs/ingests Drive files |
| User-facing value | User searches/chats over ingested Drive content |
| Disconnect | User can disconnect Google Drive |
| No Google login | OpenRAG login is separate from Drive authorization |

---

## 5. Privacy policy

Your privacy policy should include the Google Drive connector section you already drafted.

It must explain:

| Topic | What to disclose |
|---|---|
| What data is accessed | Drive files and metadata |
| Why it is accessed | Ingestion, indexing, search, retrieval, chat/RAG |
| What is stored | Metadata, extracted text, chunks, embeddings, index records |
| Token storage | Refresh tokens stored securely |
| What is not done | No Drive write/delete/modify |
| Sharing | Subprocessors/model providers if applicable |
| Human access | Limited support/security access |
| Deletion | How users/admins delete indexed Drive data |
| Disconnect | How users disconnect/revoke Drive access |
| Limited Use | No advertising, no selling, no unrelated transfer |

---

## 6. Data-flow / architecture diagram

This is especially important for restricted-scope review.

Provide a diagram like:

```text
OpenRAG authenticated user
        ↓
OpenRAG Google Drive connector UI
        ↓
Google OAuth consent
        ↓
OpenRAG OAuth callback
        ↓
Encrypted refresh token storage
        ↓
Drive API read-only access
        ↓
Document download
        ↓
Docling / parsing
        ↓
Chunking / embeddings
        ↓
OpenSearch index
        ↓
OpenRAG retrieval/chat with user/tenant filters
```

This does not need to expose code. It should explain where Google Drive data and OAuth tokens go.

---

## 7. Security controls summary

Prepare this for the verification/security review:

| Control | Statement to provide |
|---|---|
| Token protection | Refresh tokens are encrypted or securely stored |
| No secret logging | Access tokens, refresh tokens, auth codes, and client secrets are not logged |
| Least privilege | Only `drive.readonly` is requested |
| No Drive writes | App does not create, modify, move, or delete Drive files |
| Access control | Indexed content is filtered by OpenRAG user/tenant/ACL |
| Data deletion | Drive-derived content can be deleted from OpenRAG |
| Disconnect | User can disconnect/revoke Drive connector |
| Monitoring | OAuth and connector errors are monitored |
| Incident response | Security contact/process exists |

---

# What you do not need to provide upfront

Usually, you do **not** need to provide Google with:

- Source code.
- Full database schema.
- Internal class names.
- Endpoint implementation details.
- Kubernetes manifests.
- Langflow implementation details.
- OpenSearch mappings, unless specifically requested.
- Internal logs.
- Customer-specific data.

You may need to provide more detailed evidence later if Google triggers a formal security assessment.

---

# Practical checklist

Since OpenRAG already has items 5 and 6 implemented, prepare these files/materials:

| File / artifact | Purpose |
|---|---|
| `scope-justification.md` | Explain why `drive.readonly` is needed |
| `oauth-flow-description.md` | Explain Connect Drive → Google consent → callback → connected |
| `data-flow-diagram.png` | Show token/data flow |
| `security-controls.md` | Token encryption, RBAC, no logging, deletion |
| `privacy-policy-url` | Public page with Drive connector data use |
| `demo-video-link` | Required for verification |
| `reviewer-instructions.md` | Step-by-step instructions for Google reviewers |
| `test-account-details` | If reviewer needs access to OpenRAG |
| `domain-verification-evidence` | Verified homepage/privacy/callback domains |

---

# Suggested message to align internally

```text
Items 5 and 6 are already implemented in OpenRAG, so for Google verification we do not need to deliver new code for those items. What we need to provide is verification evidence: a clear OAuth flow description, demo video, scope justification for drive.readonly, privacy policy language, data-flow/security documentation, and proof that tokens and Drive-derived data are handled securely.

Google will review whether the production app behavior matches the requested scope and whether our privacy/security documentation explains how Drive data is accessed, stored, used, protected, disconnected, and deleted.
```
