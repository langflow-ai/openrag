# Customer connector packages

Customer connectors are **trusted Python code** installed in a derived backend image, not uploaded into a running server. The host discovers only explicitly enabled wheels from the `openrag.connectors.v1` entry-point group. A customer package can provide authentication, complete paginated inventory, file download and (optionally) paginated folder navigation. OpenRAG supplies the generic credentials form, picker, ingestion tasks and indexing; a Python wheel cannot add a custom React popup to the already-compiled frontend.

The [SharePoint Server (NTLM) example](sharepoint_onprem/README.md) is an independently installable package demonstrating this contract. It is separate from the existing Microsoft Graph `sharepoint` connector. Keep this example **disabled** until an operator has verified the target SharePoint zone offers NTLM, approved the endpoint and CA, and exercised the tests against a non-production farm. Kerberos-only, forms, SAML and OIDC zones are not supported by this NTLM adapter.

## Build and enable

1. Implement a `BaseConnector` subclass, assign an immutable unique `CONNECTOR_TYPE`, `CONNECTOR_KIND = "bucket"` for server-side credentials, `CONNECTOR_API_VERSION = 1`, `SECRET_CONFIG_KEYS`, bounded `CONFIG_FIELDS`, and `BROWSE_CAPABILITY` (`flat` or `hierarchical`). Optionally declare `CREDENTIAL_PAIR = ("username", "password")` to require both write-only secrets to change together. Implement `authenticate`, complete paginated `list_files`, `get_file_content` and the polling lifecycle methods. A hierarchical source additionally implements `list_children(parent_id, cursor, page_size)`. Never use a picker page as the full inventory for deletion reconciliation.
   - Optional hooks (the defaults are safe):
     - Override `filename_for_index(file_id, filename)` when the indexed filename is derived from the picker name, for example keyed by source id. The duplicate check compares the returned name, so it must match what `get_file_content` indexes. Default: the name unchanged.
     - Set `REQUIRES_CONFIRMED_DELETION = True` when absence from `list_files` does not prove a deletion, for example a removed site or a permission-trimmed library. Then implement `async is_definitively_missing(file_id)` to return `True` only on positive proof, such as a 404 at the file endpoint, and `False` on any error. Orphan cleanup deletes a file only when every active connection confirms it. Default: `False`; the base `is_definitively_missing` never confirms.
     - Report `etag` (a string of at most 256 characters) on file nodes from `list_children` and file entries from `list_files`, and the same tag as `content_etag` (`CONTENT_ETAG_METADATA_KEY`) in `get_file_content` metadata. Where both exist, the picker's **Update available** compares tags and ignores timestamps; otherwise it falls back to a strictly newer `modified_time`. Report a tag only if it changes exactly when the content does and is identical across the listing and file endpoints, or every file will read as changed. A malformed `etag` is ignored.
2. Register the class under `[project.entry-points."openrag.connectors.v1"]` in your wheel's `pyproject.toml`; the entry-point name must equal `CONNECTOR_TYPE`. Build a wheel against the OpenRAG backend's Python version, pin and scan its full dependency tree, and check compatibility with the intended OpenRAG image digest. Choose a globally unique connector type; never reuse `sharepoint` (Graph) or another built-in type.
3. Produce a derived **backend** image from the approved, digest-pinned OpenRAG backend image. Install the pinned, hash-verified wheel and its dependencies into `/app/.venv` at build time (not at startup). Retain the base entrypoint: it starts as root only to fix mounted-volume ownership and then drops to `appuser` before launching Python. Example image recipe, with every dependency resolved to the offline wheelhouse:

   ```dockerfile
   ARG OPENRAG_BACKEND_IMAGE
   FROM ${OPENRAG_BACKEND_IMAGE}
   USER 0
   COPY wheelhouse/ /opt/wheels/
   COPY plugin-requirements.txt /opt/plugin-requirements.txt
   RUN python -m pip --python /app/.venv/bin/python install \
       --no-index --find-links=/opt/wheels --only-binary=:all: \
       --require-hashes --no-deps -r /opt/plugin-requirements.txt \
       && python -m pip --python /app/.venv/bin/python check \
       && rm -rf /opt/wheels /opt/plugin-requirements.txt
   ```

4. Deploy the derived backend in place of the stock backend alongside a **matching frontend image built with this generic picker feature**. Only after non-production NTLM/CA/scope acceptance, set `OPENRAG_CONNECTOR_PLUGINS=sharepoint_onprem` (or an explicit comma-separated list of approved entry-point names) **at deployment**, and mount a stable `OPENRAG_ENCRYPTION_KEY` as a runtime secret. Never bake credentials, the encryption key or customer endpoint URLs into an image. Unknown, missing or incompatible *enabled* plugins must fail startup; a disabled installed wheel must not execute or appear in the catalog. Disabling a plugin must not delete connections or indexed documents.
5. Restrict egress/DNS/CA to approved origins, create a least-privilege source account and confirm the endpoint returns the expected files. In the OpenRAG UI: open Settings → Configure → Test connection (no write) → Save → Add Knowledge → browse folders → select files → ingest → inspect tasks and indexed content. Check a changed source file, a deleted file, an inaccessible site and a failed page before rollout. Never turn a timeout or permission failure into an empty inventory or source deletion.

The initial generic picker handles navigation and file selection. A provider-native popup, browser SDK or custom React settings page needs a **second pinned npm frontend package and a derived frontend image rebuilt before Next.js compilation**. A backend wheel, runtime Python directory or arbitrary frontend script URL cannot provide that UI. Customer code executes with backend privileges; the plugin interface is not a sandbox. On SaaS, enablement requires an additional workspace approval path; do not rely on operator allowlisting alone.

## Compatibility and design rules

- Every outbound URL is derived from operator-approved config, not directly from browser-supplied file IDs, download URLs, `parent_id` or cursors. Bind all navigation/downloads to the selected connection and approved scope. Prefer verified HTTPS and a mounted private CA to a TLS bypass.
- Credentials are write-only in the browser and encrypted at rest. Reject a missing key or a failed encryption attempt rather than persisting plaintext. Status/catalog responses expose only safe metadata and secret-presence flags.
- File IDs are deterministic across pagination and restarts. If the upstream API does not offer a durable object ID, document path-ID rename/move behavior explicitly; a path-based ID changes on rename. A path-based ID must also encode the source endpoint/origin, so that identical paths on two servers never share an ID. Preserve source timestamps/version tags when reliable. Raise `FileNotFoundError` only for a definitive remote missing file. Raise ordinary errors for auth failure, out-of-scope IDs, incomplete pages and transient network failures.
- Index by connection owner unless an independently reviewed principal mapping exists. A SharePoint service account's read permission is not evidence of an OpenRAG user's SharePoint permission.
- Rebuild and restart to update or remove a wheel. Pin the wheel and base image together, run the package's behavioral tests and a deployed smoke test before promotion, and roll back by restoring the previous signed image without deleting persisted connections.

The generic UI needs no customer React code. For a custom frontend package, build a paired frontend image before Next.js compilation and version it with the connector wheel. This README and the example package's README are the portable operator contract for this PR; treat other architecture proposals as design context rather than deployed capability.
