import io
import os
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

from utils.logging_config import get_logger

from ..base import BaseConnector, ConnectorDocument, DocumentACL
from .oauth import GoogleDriveOAuth

logger = get_logger(__name__)

# -------------------------
# Config model
# -------------------------
@dataclass
class GoogleDriveConfig:
    client_id: str
    client_secret: str
    token_file: str

    # Selective sync
    file_ids: Optional[List[str]] = None
    folder_ids: Optional[List[str]] = None
    recursive: bool = True

    # Shared Drives control
    drive_id: Optional[str] = None  # when set, we use corpora='drive'
    corpora: Optional[str] = None  # 'user' | 'drive' | 'domain'; auto-picked if None

    # Optional filtering
    include_mime_types: Optional[List[str]] = None
    exclude_mime_types: Optional[List[str]] = None

    # Export overrides for Google-native types
    export_format_overrides: Optional[Dict[str, str]] = None  # mime -> export-mime

    # Changes API state persistence (store these in your DB/kv if needed)
    changes_page_token: Optional[str] = None

    # Optional: resource_id for webhook cleanup
    resource_id: Optional[str] = None


# -------------------------
# Connector implementation
# -------------------------
class GoogleDriveConnector(BaseConnector):
    """
    Google Drive connector with first-class support for selective sync:
      - Sync specific file IDs
      - Sync specific folder IDs (optionally recursive)
      - Works across My Drive and Shared Drives
      - Resolves shortcuts to their targets
      - Robust changes page token management

    Integration points:
      - `BaseConnector` is your project’s base class; minimum methods used here:
          * self.emit(doc: ConnectorDocument) -> None  (or adapt to your ingestion pipeline)
      - Adjust paths, logging, and error handling to match your project style.
    """

    # Names of env vars that hold your OAuth client creds
    CLIENT_ID_ENV_VAR: str = "GOOGLE_OAUTH_CLIENT_ID"
    CLIENT_SECRET_ENV_VAR: str = "GOOGLE_OAUTH_CLIENT_SECRET"

    # Connector metadata
    CONNECTOR_NAME = "Google Drive"
    CONNECTOR_DESCRIPTION = "Add knowledge from Google Drive"
    CONNECTOR_ICON = "google-drive"

    # Supported alias keys coming from various frontends / pickers
    _FILE_ID_ALIASES = ("file_ids", "selected_file_ids", "selected_files")
    _FOLDER_ID_ALIASES = ("folder_ids", "selected_folder_ids", "selected_folders")

    def emit(self, doc: ConnectorDocument) -> None:
        """
        Emit a ConnectorDocument instance.
        Override this method to integrate with your ingestion pipeline.
        """
        # If BaseConnector has an emit method, call super().emit(doc)
        # Otherwise, implement your custom logic here.
        logger.debug(f"Emitting document: {doc.id} ({doc.filename})")

    def __init__(self, config: Dict[str, Any]) -> None:
        # Read from config OR env (backend env, not NEXT_PUBLIC_*):
        env_client_id = os.getenv(self.CLIENT_ID_ENV_VAR)
        env_client_secret = os.getenv(self.CLIENT_SECRET_ENV_VAR)

        client_id = config.get("client_id") or env_client_id
        client_secret = config.get("client_secret") or env_client_secret

        # Token file default (so callback & workers don’t need to pass it)
        project_root = Path(__file__).resolve().parent.parent.parent.parent
        token_file = config.get("token_file") or str(
            project_root / "google_drive_token.json"
        )
        Path(token_file).parent.mkdir(parents=True, exist_ok=True)

        if not isinstance(client_id, str) or not client_id.strip():
            raise RuntimeError(
                f"Missing Google Drive OAuth client_id. "
                f"Provide config['client_id'] or set {self.CLIENT_ID_ENV_VAR}."
            )
        if not isinstance(client_secret, str) or not client_secret.strip():
            raise RuntimeError(
                f"Missing Google Drive OAuth client_secret. "
                f"Provide config['client_secret'] or set {self.CLIENT_SECRET_ENV_VAR}."
            )

        # Normalize incoming IDs from any of the supported alias keys
        def _first_present_list(
            cfg: Dict[str, Any], keys: Iterable[str]
        ) -> Optional[List[str]]:
            for k in keys:
                v = cfg.get(k)
                if v:  # accept non-empty list
                    return list(v)
            return None

        normalized_file_ids = _first_present_list(config, self._FILE_ID_ALIASES)
        normalized_folder_ids = _first_present_list(config, self._FOLDER_ID_ALIASES)

        self.cfg = GoogleDriveConfig(
            client_id=client_id,
            client_secret=client_secret,
            token_file=token_file,
            # Accept "selected_files" and "selected_folders" used by the Drive Picker flow
            file_ids=normalized_file_ids,
            folder_ids=normalized_folder_ids,
            recursive=bool(config.get("recursive", True)),
            drive_id=config.get("drive_id"),
            corpora=config.get("corpora"),
            include_mime_types=config.get("include_mime_types"),
            exclude_mime_types=config.get("exclude_mime_types"),
            export_format_overrides=config.get("export_format_overrides"),
            changes_page_token=config.get("changes_page_token"),
            resource_id=config.get("resource_id"),
        )

        # Build OAuth wrapper; DO NOT load creds here (it's async)
        self.oauth = GoogleDriveOAuth(
            client_id=self.cfg.client_id,
            client_secret=self.cfg.client_secret,
            token_file=self.cfg.token_file,
        )

        # Drive client is built in authenticate()
        from google.oauth2.credentials import Credentials

        self.creds: Optional[Credentials] = None
        self.service: Any = None

        # cache of resolved shortcutId -> target file metadata
        self._shortcut_cache: Dict[str, Dict[str, Any]] = {}

        # Authentication state
        self._authenticated: bool = False

    # -------------------------
    # Helpers
    # -------------------------
    @property
    def _drives_get_flags(self) -> Dict[str, Any]:
        """
        Flags valid for GET-like calls (files.get, changes.getStartPageToken).
        """
        return {"supportsAllDrives": True}

    @property
    def _drives_list_flags(self) -> Dict[str, Any]:
        """
        Flags valid for LIST-like calls (files.list, changes.list).
        """
        return {"supportsAllDrives": True, "includeItemsFromAllDrives": True}

    def _pick_corpora_args(self) -> Dict[str, Any]:
        """
        Decide corpora/driveId based on config.

        If drive_id is provided, prefer corpora='drive' with that driveId.
        Otherwise, default to allDrives (so Shared Drive selections from the Picker still work).
        """
        if self.cfg.drive_id:
            return {"corpora": "drive", "driveId": self.cfg.drive_id}
        if self.cfg.corpora:
            return {"corpora": self.cfg.corpora}
        # Default to allDrives so Picker selections from Shared Drives work without explicit drive_id
        return {"corpora": "allDrives"}

    def _resolve_shortcut(self, file_obj: Dict[str, Any]) -> Dict[str, Any]:
        """
        If a file is a shortcut, fetch and return the real target metadata.
        """
        if file_obj.get("mimeType") != "application/vnd.google-apps.shortcut":
            return file_obj

        target_id = file_obj.get("shortcutDetails", {}).get("targetId")
        if not target_id:
            return file_obj

        if target_id in self._shortcut_cache:
            return self._shortcut_cache[target_id]

        try:
            meta = (
                self.service.files()
                .get(
                    fileId=target_id,
                    fields=(
                        "id, name, mimeType, modifiedTime, createdTime, size, "
                        "webViewLink, parents, owners, driveId"
                    ),
                    **self._drives_get_flags,
                )
                .execute()
            )
            self._shortcut_cache[target_id] = meta
            return meta
        except HttpError:
            # shortcut target not accessible
            return file_obj

    def _list_children(self, folder_id: str) -> List[Dict[str, Any]]:
        """
        List immediate children of a folder.
        """
        query = f"'{folder_id}' in parents and trashed = false"
        page_token = None
        results: List[Dict[str, Any]] = []

        while True:
            resp = (
                self.service.files()
                .list(
                    q=query,
                    pageSize=1000,
                    pageToken=page_token,
                    fields=(
                        "nextPageToken, files("
                        "id, name, mimeType, modifiedTime, createdTime, size, "
                        "webViewLink, parents, shortcutDetails, driveId)"
                    ),
                    **self._drives_list_flags,
                    **self._pick_corpora_args(),
                )
                .execute()
            )
            for f in resp.get("files", []):
                results.append(f)
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        return results

    def _bfs_expand_folders(self, folder_ids: Iterable[str]) -> List[Dict[str, Any]]:
        """
        Breadth-first traversal to expand folders to all descendant files (if recursive),
        or just immediate children (if not recursive). Folders themselves are returned
        as items too, but filtered later.
        """
        out: List[Dict[str, Any]] = []
        queue = deque(folder_ids)

        while queue:
            fid = queue.popleft()
            children = self._list_children(fid)
            out.extend(children)

            if self.cfg.recursive:
                # Enqueue subfolders
                for c in children:
                    c = self._resolve_shortcut(c)
                    if c.get("mimeType") == "application/vnd.google-apps.folder":
                        queue.append(c["id"])

        return out

    def _get_file_meta_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch metadata for a file by ID (resolving shortcuts).
        """
        if self.service is None:
            raise RuntimeError(
                "Google Drive service is not initialized. Please authenticate first."
            )
        try:
            meta = (
                self.service.files()
                .get(
                    fileId=file_id,
                    fields=(
                        "id, name, mimeType, modifiedTime, createdTime, size, "
                        "webViewLink, parents, shortcutDetails, driveId"
                    ),
                    **self._drives_get_flags,
                )
                .execute()
            )
            return self._resolve_shortcut(meta)
        except HttpError:
            return None

    def _filter_by_mime(self, items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Apply include/exclude mime filters if configured.
        """
        include = set(self.cfg.include_mime_types or [])
        exclude = set(self.cfg.exclude_mime_types or [])

        def keep(m: Dict[str, Any]) -> bool:
            mt = m.get("mimeType")
            if exclude and mt in exclude:
                return False
            if include and mt not in include:
                return False
            return True

        return [m for m in items if keep(m)]

    def _iter_selected_items(self) -> List[Dict[str, Any]]:
        """
        Return a de-duplicated list of file metadata for the selected scope:
          - explicit file_ids (automatically expands folders to their contents)
          - items inside folder_ids (with optional recursion)
        Shortcuts are resolved to their targets automatically.
        """
        seen: Set[str] = set()
        items: List[Dict[str, Any]] = []
        folders_to_expand: List[str] = []

        # Process file_ids: separate actual files from folders
        if self.cfg.file_ids:
            for fid in self.cfg.file_ids:
                meta = self._get_file_meta_by_id(fid)
                if not meta:
                    continue

                # If it's a folder, add to folders_to_expand instead
                if meta.get("mimeType") == "application/vnd.google-apps.folder":
                    logger.debug(
                        f"Item {fid} ({meta.get('name')}) is a folder, "
                        f"will expand to contents"
                    )
                    folders_to_expand.append(fid)
                elif meta["id"] not in seen:
                    # It's a regular file, add it directly
                    seen.add(meta["id"])
                    items.append(meta)

        # Collect all folders to expand (from both file_ids and folder_ids)
        if self.cfg.folder_ids:
            folders_to_expand.extend(self.cfg.folder_ids)

        # Expand all folders to their contents
        if folders_to_expand:
            folder_children = self._bfs_expand_folders(folders_to_expand)
            for meta in folder_children:
                meta = self._resolve_shortcut(meta)
                if meta.get("id") in seen:
                    continue
                seen.add(meta["id"])
                items.append(meta)

        # If neither file_ids nor folder_ids are set, you could:
        #  - return [] to force explicit selection
        #  - OR default to entire drive.
        # Here we choose to require explicit selection:
        if not self.cfg.file_ids and not self.cfg.folder_ids:
            return []

        items = self._filter_by_mime(items)
        # Exclude folders from final emits:
        items = [
            m
            for m in items
            if m.get("mimeType") != "application/vnd.google-apps.folder"
        ]
        return items

    # -------------------------
    # Download logic
    # -------------------------
    def _pick_export_mime(self, source_mime: str) -> Optional[str]:
        """
        Choose export mime for Google-native docs if needed.
        """
        overrides = self.cfg.export_format_overrides or {}
        if source_mime == "application/vnd.google-apps.document":
            return overrides.get(
                source_mime,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        if source_mime == "application/vnd.google-apps.spreadsheet":
            return overrides.get(
                source_mime,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        if source_mime == "application/vnd.google-apps.presentation":
            return overrides.get(
                source_mime,
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        # Return None for non-Google-native or unsupported types
        return overrides.get(source_mime)

    def _download_file_bytes(self, file_meta: Dict[str, Any]) -> bytes:
        """
        Download bytes for a given file (exporting if Google-native).
        Raises ValueError if the item is a folder (folders cannot be downloaded).
        """
        file_id = file_meta["id"]
        file_name = file_meta.get("name", "unknown")
        mime_type = file_meta.get("mimeType") or ""

        logger.debug(
            f"Downloading file {file_id} ({file_name}) with mimetype: {mime_type}"
        )

        # Folders cannot be downloaded or exported - this should never be reached
        # as folders are automatically expanded in _iter_selected_items()
        if mime_type == "application/vnd.google-apps.folder":
            raise ValueError(
                f"Cannot download folder {file_id} ({file_name}). "
                f"This is a bug - folders should be automatically expanded before download."
            )

        # According to https://stackoverflow.com/questions/65053558/google-drive-api-v3-files-export-method-throws-a-403-error-export-only-support
        # export_media ONLY works for Google Docs Editors files (Docs, Sheets, Slides, Drawings)
        # All other files (including other Google Apps types like Forms, Sites, Maps) must use get_media

        # Define which Google Workspace files are exportable
        exportable_types = {
            "application/vnd.google-apps.document",  # Google Docs
            "application/vnd.google-apps.spreadsheet",  # Google Sheets
            "application/vnd.google-apps.presentation",  # Google Slides
            "application/vnd.google-apps.drawing",  # Google Drawings
        }

        if mime_type in exportable_types:
            # This is an exportable Google Workspace file - must use export_media
            export_mime = self._pick_export_mime(mime_type)
            if not export_mime:
                # Default fallback for unsupported Google native types
                export_mime = "application/pdf"

            logger.debug(
                f"Using export_media for {file_id} ({mime_type} -> {export_mime})"
            )
            # NOTE: export_media does not accept supportsAllDrives/includeItemsFromAllDrives
            request = self.service.files().export_media(
                fileId=file_id, mimeType=export_mime
            )
        else:
            # This is a regular uploaded file (PDF, image, video, etc.) - use get_media
            # Also handles non-exportable Google Apps files (Forms, Sites, Maps, etc.)
            logger.debug(f"Using get_media for {file_id} ({mime_type})")
            # Binary download (get_media also doesn't accept the Drive flags)
            request = self.service.files().get_media(fileId=file_id)

        # Download the file with error handling for misclassified Google Docs
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024)
        done = False

        try:
            while not done:
                status, done = downloader.next_chunk()
                # Optional: you can log progress via status.progress()
        except HttpError as e:
            # If download fails with "fileNotDownloadable", it's a Docs Editor file
            # that wasn't properly detected. Retry with export_media.
            if "fileNotDownloadable" in str(e) and mime_type not in exportable_types:
                logger.warning(
                    f"Download failed for {file_id} ({mime_type}) with fileNotDownloadable error. "
                    f"Retrying with export_media (file might be a Google Doc)"
                )
                export_mime = "application/pdf"
                request = self.service.files().export_media(
                    fileId=file_id, mimeType=export_mime
                )
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request, chunksize=1024 * 1024)
                done = False
                while not done:
                    status, done = downloader.next_chunk()
            else:
                raise

        return fh.getvalue()

    # -------------------------
    # Public sync surface
    # -------------------------
    # ---- Required by BaseConnector: start OAuth flow
    async def authenticate(self) -> bool:
        """
        Ensure we have valid Google Drive credentials and an authenticated service.
        Returns True if ready to use; False otherwise.
        """
        try:
            # Load/refresh creds from token file (async)
            self.creds = await self.oauth.load_credentials()

            # If still not authenticated, bail (caller should kick off OAuth init)
            if not await self.oauth.is_authenticated():
                logger.debug(
                    "authenticate: no valid credentials; run OAuth init/callback first."
                )
                return False

            # Build Drive service from OAuth helper
            self.service = self.oauth.get_service()

            # Optional sanity check (small, fast request)
            _ = self.service.files().get(fileId="root", fields="id").execute()
            self._authenticated = True
            return True

        except Exception as e:
            self._authenticated = False
            logger.error(f"GoogleDriveConnector.authenticate failed: {e}")
            return False

    async def list_files(
        self,
        page_token: Optional[str] = None,
        max_files: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        List files in the currently selected scope (file_ids/folder_ids/recursive).
        Returns a dict with 'files' and 'next_page_token'.

        Since we pre-compute the selected set, pagination is simulated:
        - If page_token is None: return all files in one batch.
        - Otherwise: return {} and no next_page_token.
        """
        try:
            items = self._iter_selected_items()

            # Optionally honor a request-scoped max_files (e.g., from your API payload)
            if isinstance(max_files, int) and max_files > 0:
                items = items[:max_files]

            # Simplest: ignore page_token and just dump all
            # If you want real pagination, slice items here
            if page_token:
                return {"files": [], "next_page_token": None}

            return {
                "files": items,
                "next_page_token": None,  # no more pages
            }
        except Exception as e:
            # Log the error
            try:
                logger.error(f"GoogleDriveConnector.list_files failed: {e}")
            except Exception:
                pass
            return {"files": [], "next_page_token": None}

    async def get_file_content(self, file_id: str) -> ConnectorDocument:
        """
        Fetch a file's metadata and content from Google Drive and wrap it in a ConnectorDocument.
        Raises FileNotFoundError if the ID is a folder (folders cannot be downloaded).
        """
        meta = self._get_file_meta_by_id(file_id)
        if not meta:
            raise FileNotFoundError(f"Google Drive file not found: {file_id}")

        # Check if this is a folder - folders cannot be downloaded
        if meta.get("mimeType") == "application/vnd.google-apps.folder":
            raise FileNotFoundError(
                f"Cannot download folder {file_id} ({meta.get('name')}). "
                f"Folders must be expanded to list their contents. "
                f"This ID should not have been passed to get_file_content()."
            )

        try:
            blob = self._download_file_bytes(meta)
        except Exception as e:
            try:
                logger.error(f"Download failed for {file_id}: {e}")
            except Exception:
                pass
            raise

        from datetime import datetime

        def parse_datetime(dt_str):
            if not dt_str:
                return None
            try:
                # Google Drive returns RFC3339 format
                return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError:
                try:
                    return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%SZ")
                except ValueError:
                    return None

        doc = ConnectorDocument(
            id=meta["id"],
            filename=meta.get("name", ""),
            source_url=meta.get("webViewLink", ""),
            created_time=parse_datetime(meta.get("createdTime")),
            modified_time=parse_datetime(meta.get("modifiedTime")),
            mimetype=str(meta.get("mimeType", "")),
            acl=DocumentACL(),  # TODO: map Google Drive permissions if you want ACLs
            content=blob,
            metadata={
                "parents": meta.get("parents"),
                "driveId": meta.get("driveId"),
                "size": int(meta.get("size", 0))
                if str(meta.get("size", "")).isdigit()
                else None,
            },
        )
        return doc

    async def setup_subscription(self) -> str:
        """
        Start a Google Drive Changes API watch (webhook).
        Returns the channel ID (subscription ID) as a string.

        Requires a webhook URL to be configured. This implementation looks for:
        1) self.cfg.webhook_address (preferred if you have it in your config dataclass)
        2) os.environ["GOOGLE_DRIVE_WEBHOOK_URL"]
        """
        import os

        # 1) Ensure we are authenticated and have a live Drive service
        ok = await self.authenticate()
        if not ok:
            raise RuntimeError(
                "GoogleDriveConnector.setup_subscription: not authenticated"
            )

        # 2) Resolve webhook address (no param in ABC, so pull from config/env)
        webhook_address = getattr(self.cfg, "webhook_address", None) or os.getenv(
            "GOOGLE_DRIVE_WEBHOOK_URL"
        )
        if not webhook_address:
            raise RuntimeError(
                "GoogleDriveConnector.setup_subscription: webhook URL not configured. "
                "Set cfg.webhook_address or GOOGLE_DRIVE_WEBHOOK_URL."
            )

        # 3) Ensure we have a starting page token (checkpoint)
        try:
            if not self.cfg.changes_page_token:
                self.cfg.changes_page_token = self.get_start_page_token()
        except Exception as e:
            try:
                logger.error(f"Failed to get start page token: {e}")
            except Exception:
                pass
            raise

        # 4) Start the watch on the current token
        try:
            # Build a simple watch body; customize id if you want a stable deterministic value
            body = {
                "id": f"drive-channel-{int(time.time())}",  # subscription (channel) ID to return
                "type": "web_hook",
                "address": webhook_address,
            }

            # Shared Drives flags so we see everything we’re scoped to
            flags = dict(supportsAllDrives=True)

            result = (
                self.service.changes()
                .watch(pageToken=self.cfg.changes_page_token, body=body, **flags)
                .execute()
            )

            # Example fields: id, resourceId, expiration, kind
            channel_id = result.get("id")
            resource_id = result.get("resourceId")
            expiration = result.get("expiration")

            # Persist in-memory so cleanup can stop this channel later.
            self._active_channel = {
                "channel_id": channel_id,
                "resource_id": resource_id,
                "expiration": expiration,
                "webhook_address": webhook_address,
                "page_token": self.cfg.changes_page_token,
            }

            if not isinstance(channel_id, str) or not channel_id:
                raise RuntimeError(
                    f"Drive watch returned invalid channel id: {channel_id!r}"
                )

            return channel_id

        except Exception as e:
            try:
                logger.error(f"GoogleDriveConnector.setup_subscription failed: {e}")
            except Exception:
                pass
            raise

    async def cleanup_subscription(self, subscription_id: str) -> bool:
        """
        Stop an active Google Drive Changes API watch (webhook) channel.

        Google requires BOTH the channel id (subscription_id) AND its resource_id.
        We try to retrieve resource_id from:
        1) self._active_channel (single-channel use)
        2) self._subscriptions[subscription_id] (multi-channel use, if present)
        3) self.cfg.resource_id (as a last-resort override provided by caller/config)

        Returns:
            bool: True if the stop call succeeded, otherwise False.
        """
        # 1) Ensure auth/service
        ok = await self.authenticate()
        if not ok:
            try:
                logger.error("cleanup_subscription: not authenticated")
            except Exception:
                pass
            return False

        # 2) Resolve resource_id
        resource_id = None

        # Single-channel memory
        if getattr(self, "_active_channel", None):
            ch = getattr(self, "_active_channel")
            if isinstance(ch, dict) and ch.get("channel_id") == subscription_id:
                resource_id = ch.get("resource_id")

        # Multi-channel memory
        if resource_id is None and hasattr(self, "_subscriptions"):
            subs = getattr(self, "_subscriptions")
            if isinstance(subs, dict):
                entry = subs.get(subscription_id)
                if isinstance(entry, dict):
                    resource_id = entry.get("resource_id")

        # Config override (optional)
        if resource_id is None and getattr(self.cfg, "resource_id", None):
            resource_id = self.cfg.resource_id

        if not resource_id:
            try:
                logger.error(
                    f"cleanup_subscription: missing resource_id for channel {subscription_id}. "
                    f"Persist (channel_id, resource_id) when creating the subscription."
                )
            except Exception:
                pass
            return False

        try:
            self.service.channels().stop(
                body={"id": subscription_id, "resourceId": resource_id}
            ).execute()

            # 4) Clear local bookkeeping
            if (
                getattr(self, "_active_channel", None)
                and self._active_channel.get("channel_id") == subscription_id
            ):
                self._active_channel = {}

            if hasattr(self, "_subscriptions") and isinstance(
                self._subscriptions, dict
            ):
                self._subscriptions.pop(subscription_id, None)

            return True

        except Exception as e:
            try:
                logger.error(f"cleanup_subscription failed for {subscription_id}: {e}")
            except Exception:
                pass
            return False

    async def handle_webhook(self, payload: Dict[str, Any]) -> List[str]:
        """
        Process a Google Drive Changes webhook.
        Drive push notifications do NOT include the changed files themselves; they merely tell us
        "there are changes". We must pull them using the Changes API with our saved page token.

        Args:
            payload: Arbitrary dict your framework passes. We *may* log/use headers like
                    X-Goog-Resource-State / X-Goog-Message-Number if present, but we don't rely on them.

        Returns:
            List[str]: unique list of affected file IDs (filtered to our selected scope).
        """
        affected: List[str] = []
        try:
            # 1) Ensure we're authenticated / service ready
            ok = await self.authenticate()
            if not ok:
                try:
                    logger.error("handle_webhook: not authenticated")
                except Exception:
                    pass
                return affected

            # 2) Establish/restore our checkpoint page token
            page_token = self.cfg.changes_page_token
            if not page_token:
                # First time / missing state: initialize
                page_token = self.get_start_page_token()
                self.cfg.changes_page_token = page_token

            # 3) Build current selected scope to filter changes
            #    (file_ids + expanded folder descendants)
            try:
                selected_items = self._iter_selected_items()
                selected_ids = {m["id"] for m in selected_items}
            except Exception as e:
                selected_ids = set()
                try:
                    logger.error(
                        f"handle_webhook: scope build failed, proceeding unfiltered: {e}"
                    )
                except Exception:
                    pass

            # 4) Pull changes until nextPageToken is exhausted, then advance to newStartPageToken
            while True:
                resp = (
                    self.service.changes()
                    .list(
                        pageToken=page_token,
                        fields=(
                            "nextPageToken, newStartPageToken, "
                            "changes(fileId, file(id, name, mimeType, trashed, parents, "
                            "shortcutDetails, driveId, modifiedTime, webViewLink))"
                        ),
                        supportsAllDrives=True,
                        includeItemsFromAllDrives=True,
                    )
                    .execute()
                )

                for ch in resp.get("changes", []):
                    fid = ch.get("fileId")
                    fobj = ch.get("file") or {}

                    # Skip if no file or explicitly trashed (you can choose to still return these IDs)
                    if not fid or fobj.get("trashed"):
                        # If you want to *include* deletions, collect fid here instead of skipping.
                        continue

                    # Resolve shortcuts to target
                    resolved = self._resolve_shortcut(fobj)
                    rid = resolved.get("id", fid)

                    # Filter to our selected scope if we have one; otherwise accept all
                    if selected_ids and (rid not in selected_ids):
                        # Shortcut target might be in scope even if the shortcut isn't
                        tgt = (
                            fobj.get("shortcutDetails", {}).get("targetId")
                            if fobj
                            else None
                        )
                        if not (tgt and tgt in selected_ids):
                            continue

                    affected.append(rid)

                # Handle pagination of the changes feed
                next_token = resp.get("nextPageToken")
                if next_token:
                    page_token = next_token
                    continue

                # No nextPageToken: checkpoint with newStartPageToken
                new_start = resp.get("newStartPageToken")
                if new_start:
                    self.cfg.changes_page_token = new_start
                else:
                    # Fallback: keep the last consumed token if API didn't return newStartPageToken
                    self.cfg.changes_page_token = page_token
                break

            # Deduplicate while preserving order
            seen = set()
            deduped: List[str] = []
            for x in affected:
                if x not in seen:
                    seen.add(x)
                    deduped.append(x)
            return deduped

        except Exception as e:
            try:
                logger.error(f"handle_webhook failed: {e}")
            except Exception:
                pass
            return []

    def sync_once(self) -> None:
        """
        Perform a one-shot sync of the currently selected scope and emit documents.

        Emits ConnectorDocument instances
        """
        items = self._iter_selected_items()
        for meta in items:
            try:
                blob = self._download_file_bytes(meta)
            except HttpError as e:
                # Skip/record failures
                logger.error(
                    f"Failed to download {meta.get('name')} ({meta.get('id')}): {e}"
                )
                continue

            from datetime import datetime

            def parse_datetime(dt_str):
                if not dt_str:
                    return None
                try:
                    # Google Drive returns RFC3339 format
                    return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S.%fZ")
                except ValueError:
                    try:
                        return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%SZ")
                    except ValueError:
                        return None

            doc = ConnectorDocument(
                id=meta["id"],
                filename=meta.get("name", ""),
                source_url=meta.get("webViewLink", ""),
                created_time=parse_datetime(meta.get("createdTime")),
                modified_time=parse_datetime(meta.get("modifiedTime")),
                mimetype=str(meta.get("mimeType", "")),
                acl=DocumentACL(),  # TODO: set appropriate ACL instance or value
                metadata={
                    "name": meta.get("name"),
                    "webViewLink": meta.get("webViewLink"),
                    "parents": meta.get("parents"),
                    "driveId": meta.get("driveId"),
                    "size": int(meta.get("size", 0))
                    if str(meta.get("size", "")).isdigit()
                    else None,
                },
                content=blob,
            )
            self.emit(doc)

    # -------------------------
    # Changes API (polling or webhook-backed)
    # -------------------------
    def get_start_page_token(self) -> str:
        # getStartPageToken accepts supportsAllDrives (not includeItemsFromAllDrives)
        resp = (
            self.service.changes().getStartPageToken(**self._drives_get_flags).execute()
        )
        return resp["startPageToken"]

    def poll_changes_and_sync(self) -> Optional[str]:
        """
        Incrementally process changes since the last page token in cfg.changes_page_token.

        Returns the new page token you should persist (or None if unchanged).
        """
        page_token = self.cfg.changes_page_token or self.get_start_page_token()

        while True:
            resp = (
                self.service.changes()
                .list(
                    pageToken=page_token,
                    fields=(
                        "nextPageToken, newStartPageToken, "
                        "changes(fileId, file(id, name, mimeType, trashed, parents, "
                        "shortcutDetails, driveId, modifiedTime, webViewLink))"
                    ),
                    **self._drives_list_flags,
                )
                .execute()
            )

            changes = resp.get("changes", [])

            # Filter to our selected scope (files and folder descendants):
            selected_ids = {m["id"] for m in self._iter_selected_items()}
            for ch in changes:
                fid = ch.get("fileId")
                file_obj = ch.get("file") or {}
                if not fid or not file_obj or file_obj.get("trashed"):
                    continue

                # Match scope
                if fid not in selected_ids:
                    # also consider shortcut target
                    if (
                        file_obj.get("mimeType")
                        == "application/vnd.google-apps.shortcut"
                    ):
                        tgt = file_obj.get("shortcutDetails", {}).get("targetId")
                        if tgt and tgt in selected_ids:
                            pass
                        else:
                            continue

                # Download and emit the updated file
                resolved = self._resolve_shortcut(file_obj)
                try:
                    blob = self._download_file_bytes(resolved)
                except HttpError:
                    continue

                from datetime import datetime

                def parse_datetime(dt_str):
                    if not dt_str:
                        return None
                    try:
                        return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S.%fZ")
                    except ValueError:
                        try:
                            return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%SZ")
                        except ValueError:
                            return None

                doc = ConnectorDocument(
                    id=resolved["id"],
                    filename=resolved.get("name", ""),
                    source_url=resolved.get("webViewLink", ""),
                    created_time=parse_datetime(resolved.get("createdTime")),
                    modified_time=parse_datetime(resolved.get("modifiedTime")),
                    mimetype=str(resolved.get("mimeType", "")),
                    acl=DocumentACL(),  # Set appropriate ACL if needed
                    metadata={
                        "parents": resolved.get("parents"),
                        "driveId": resolved.get("driveId"),
                    },
                    content=blob,
                )
                self.emit(doc)

            new_page_token = resp.get("nextPageToken")
            if new_page_token:
                page_token = new_page_token
                continue

            # No nextPageToken: advance to newStartPageToken (checkpoint)
            new_start = resp.get("newStartPageToken")
            if new_start:
                self.cfg.changes_page_token = new_start
                return new_start

            # Should not happen often
            return page_token

    # -------------------------
    # Optional: webhook stubs
    # -------------------------
    def build_watch_body(
        self, webhook_address: str, channel_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Prepare the request body for changes.watch if you use webhooks.
        """
        return {
            "id": channel_id or f"drive-channel-{int(time.time())}",
            "type": "web_hook",
            "address": webhook_address,
        }

    def start_watch(self, webhook_address: str) -> Dict[str, Any]:
        """
        Start a webhook watch on changes using the current page token.
        Persist the returned resourceId/expiration on your side.
        """
        page_token = self.cfg.changes_page_token or self.get_start_page_token()
        body = self.build_watch_body(webhook_address)
        result = (
            self.service.changes()
            .watch(pageToken=page_token, body=body, **self._drives_get_flags)
            .execute()
        )
        return result

    def stop_watch(self, channel_id: str, resource_id: str) -> bool:
        """
        Stop a previously started webhook watch.
        """
        try:
            self.service.channels().stop(
                body={"id": channel_id, "resourceId": resource_id}
            ).execute()
            return True

        except HttpError as e:
            logger.error("Failed to cleanup subscription", error=str(e))

            return False
