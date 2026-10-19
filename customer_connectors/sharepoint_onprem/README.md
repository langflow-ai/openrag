# SharePoint Server on-premises (NTLM) example connector

`openrag-sharepoint-onprem` is a separately packaged `sharepoint_onprem` adapter. It uses SharePoint Server REST and NTLM with **server-side** credentials; it does not use Microsoft Graph, SharePoint Online OAuth or the existing `sharepoint` browser popup. The generic OpenRAG form/picker displays configured sites, document libraries, nested folders and files, and sends selected file IDs to the backend for ingestion. It never sends the NTLM password to browser code except when the authorized user explicitly submits Test or Save over the OpenRAG HTTPS connection. This connector indexes documents for the **OpenRAG connection owner only**; it does not inherit SharePoint/AD ACLs.

**Release gate:** no real SharePoint farm is supplied with this repository. Tests using simulated REST responses cannot prove NTLM handshake, selected farm's REST capability, custom CA, nested library permissions or >500-item paging on that farm. Enable this package only in an isolated non-production environment to perform the acceptance below; do not enable it in production until that gate passes. This is a draft integration, not a claim of live-farm certification.

## Preconditions

- SharePoint Server web-application zone offers **NTLM** and REST, with a least-privilege read-only Windows service identity permitted to the nominated sites and document libraries. Kerberos-only, FBA, SAML, OIDC or Graph-only endpoints are not supported; no Basic fallback. Confirm the challenge from inside the backend network before rollout.
- Backend egress/DNS is limited to the approved intranet origin. For a private SharePoint CA, mount an operator-managed **PEM CA bundle** in the backend container and set `OPENRAG_SHAREPOINT_CA_BUNDLE` to its absolute, readable regular-file path. The adapter passes that bundle explicitly to Requests TLS verification; if unset, Requests uses its default CA bundle. TLS verification cannot be disabled. Its HTTP session ignores proxy/CA environment variables (`trust_env=False`), so `REQUESTS_CA_BUNDLE` is not a supported configuration route.
- `OPENRAG_SHAREPOINT_ALLOWED_ORIGINS` is a comma- or newline-separated list of **exact approved HTTPS origins** (scheme, DNS name and optional port, not arbitrary URLs). Every configured `root_url` must match one origin. No redirect is followed and file IDs cannot name arbitrary fetch URLs. Also enforce egress/DNS policy outside Python to mitigate DNS rebinding.
- A stable `OPENRAG_ENCRYPTION_KEY` is mounted at runtime; the host rejects missing or failed plugin-secret encryption. Preserve it for restart/restore. The package is installed into `/app/.venv` in an immutable derived backend image, and `OPENRAG_CONNECTOR_PLUGINS=sharepoint_onprem` is enabled in production **only after** the test farm gate.

## Build

The package entry point is `openrag.connectors.v1:sharepoint_onprem`, exports `SharePointOnPremConnector` and declares dependencies `requests>=2.31,<3` and `requests-ntlm>=1.3,<2`. Build and install a hash-pinned offline wheelhouse using the parent [customer connector guide](../README.md). The built-in Graph connector remains unchanged; do not modify OpenRAG's `src/connectors/registry.py` for this wheel.

## Local development (explicit opt-in)

`make backend` starts the stock backend: it does not install or enable customer wheels, so `make frontend` alone cannot add this card to Settings → Connectors. After stopping the existing host backend, use the dedicated target from the repository root:

```bash
make backend-sharepoint-onprem  # in one terminal; syncs the venv, installs this package, enables it
make frontend                  # in another terminal
```

The card should appear at `http://localhost:3000/settings/connectors` even before configuring a connection. The **Test connection** and **Save** actions require a reachable, approved SharePoint farm, a valid NTLM account, `OPENRAG_SHAREPOINT_ALLOWED_ORIGINS` and a stable `OPENRAG_ENCRYPTION_KEY` in your private `.env`; set `OPENRAG_SHAREPOINT_CA_BUNDLE` for a private CA. Do not invent a permissive origin or disable TLS just to exercise the form. `make backend` neither installs the customer package nor enables its allowlist: restart with `make backend-sharepoint-onprem` to use this opt-in. The dedicated target installs the package *after* syncing the venv and uses `uv run --no-sync` to keep it available to the backend process. Production deployments use the pinned derived-image procedure in the parent guide, not an editable development install.

The operator configures a connection in OpenRAG Settings after the approved wheel is loaded:

| Field | Meaning |
|---|---|
| `root_url` | HTTPS SharePoint web-application root (may include its approved base path); no username, query or fragment. |
| `username` / `password` | NTLM service identity; write-only secrets, masked on subsequent edits. Both must be supplied together for a new connection; an omitted pair reuses saved values on edit. |
| `domain` | Optional NTLM domain (e.g. `CONTOSO`). |
| `site_paths` | One nominated site path **per line**, relative to `root_url`, e.g. `sites/finance`. No farm-wide discovery or implicit all-sites choice; saving an empty selection is rejected. |

Select **Test connection** to authenticate and check the specified scope without persisting. **Save** revalidates and stores encrypted credentials and nominated sites. In Add Knowledge, navigate the configured site → its visible document libraries → folders → files. Use **Load more** to reach subsequent pages, select files across folder/page transitions, and ingest the selected IDs under the exact connection. Reopen the picker to inspect the indexed state; use regular connector re-sync for changed or removed source files. The first version supports **file selection, not recursive folder selection or full-farm ingest**; opening a folder never starts ingestion.

## Known limits and safety

- Configured site paths are explicit because SharePoint farm-wide Search/site discovery is not universally enabled. Hidden/system libraries should not appear; an inaccessible site or a failed page is an error, **not** an empty successful inventory. A user cannot browse or download a file outside the persisted selected sites/libraries.
- The adapter caps downloads at **50 MiB**, serves at most **200 picker nodes per page** and at most **1,000 files per inventory call** with pagination. Operators must validate very large libraries and traversal cost against their farm before enabling scheduled resync.
- SharePoint's legacy `GetFolderByServerRelativeUrl`/`GetFileByServerRelativeUrl` REST endpoints do not handle `#` or `%` correctly in names. This version **rejects those paths** rather than ingesting the wrong document; ResourcePath API support requires a subsequent reviewed implementation. Index visibility is owner-only, not SharePoint ACL parity; do not enable sharing for this source.
- Source 401/403, timeout, invalid input, unexpected redirect or incomplete enumeration never signal deletion. Removing a configured `site_paths` entry or losing visibility of a document library leaves previously indexed files untouched: an ordinary re-sync only removes a missing file after a 404 from its scoped file endpoint while the site and library remain visible. Removing access is **not** a way to purge the index; use authorized OpenRAG deletion for intentional removal. A source ID is opaque to clients and revalidated against configured origin/site/library at use time.
- IDs are deterministic for a file at the same server-relative path across paging and restarts, but **rename/move changes the ID**. A re-sync sees the old path removed and the new path as a distinct file; review retention and duplicate handling before use where renames are frequent. This is not a durable SharePoint GUID mapping.
- The picker displays natural SharePoint basenames; indexed filenames carry a stable source-ID suffix before the extension so `team/report.pdf` and `finance/report.pdf` can coexist. The duplicate dialog checks those indexed names, not the shared basename.
- No webhooks or subscription events: updates use explicit or scheduled polling/re-sync. The host remains single-worker until its process-local permission caches are replaced.

## Non-production acceptance before promotion

1. From the **derived backend image** with `OPENRAG_SHAREPOINT_CA_BUNDLE` mounted for a private CA, authenticate with the approved NTLM account against the actual zone. Verify the unauthorized, expired-secret, TLS failure and cross-origin redirect cases fail safely, without logging a password or URL containing credentials.
2. Test/Save a nominated site and a second inaccessible site; only the selected, readable scope is navigable. Test should not create a connection. Restart and verify saved secrets decrypt and the connection still works. Inspect `connections.json`: no plaintext username or password.
3. Browse a library with nested folders, duplicate filenames and **more than 500 entries**, selecting files from distinct pages. Ingest; verify tasks and indexed content are owner-only. A forged `parent_id`, cursor, file ID, wrong connection ID and another OpenRAG user's connection must be rejected.
4. Change and remove indexed files and re-sync; verify changed content replaces stale chunks and a definitive deletion removes its chunks. Revoke access or cause a timeout mid-enumeration and verify **no** indexed documents are deleted. Roll back the derived image to the prior signed version without losing saved connections or documents.

If the farm uses Kerberos-only or a different identity zone, stop: a simulated test cannot turn it into an NTLM-capable connector. The Microsoft [SharePoint Server authentication overview](https://learn.microsoft.com/en-us/sharepoint/security-for-sharepoint-server/authentication-overview) describes the zone prerequisites; the [SharePoint REST folder/file guide](https://learn.microsoft.com/en-us/sharepoint/dev/sp-add-ins/working-with-folders-and-files-with-rest) documents the legacy URL-encoding restriction.
