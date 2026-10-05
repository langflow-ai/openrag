"""SharePoint Server REST connector. Only explicitly configured sites are discoverable.

Requires OPENRAG_SHAREPOINT_ALLOWED_ORIGINS to contain the server's HTTPS origin.
IDs encode server-relative paths, but are not authorization tokens: every use is
checked against configured sites and the server's current document libraries.
"""

import asyncio
import base64
import hashlib
import json
import mimetypes
import os
from collections import deque
from datetime import UTC, datetime
from urllib.parse import parse_qsl, quote, unquote, urlsplit

import requests
from requests_ntlm import HttpNtlmAuth

from connectors.base import BaseConnector, ConnectorDocument, DocumentACL

_MAX_METADATA_BYTES = 4 * 1024 * 1024
_MAX_FILE_BYTES = 50 * 1024 * 1024
_MAX_TOKEN_BYTES = 256 * 1024
_PAGE_SIZE = 200
_TIMEOUT = (5, 20)  # connection, read (seconds)


def _token(value):
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(raw) > _MAX_TOKEN_BYTES:
        raise ValueError("SharePoint continuation is too large")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _untoken(value):
    if not isinstance(value, str) or not value or len(value) > 4 * _MAX_TOKEN_BYTES // 3 + 8:
        raise ValueError("Invalid SharePoint identifier or cursor")
    try:
        raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        decoded = json.loads(raw)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid SharePoint identifier or cursor") from exc
    if _token(decoded) != value:
        raise ValueError("Invalid SharePoint identifier or cursor")
    return decoded


def _origin(url, *, allow_query=False):
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or (parts.query and not allow_query)
        or parts.fragment
        or parts.port == 0
    ):
        raise ValueError("SharePoint requires an approved HTTPS origin")
    return f"https://{parts.netloc.lower()}"


def _segments(path):
    if not isinstance(path, str) or "#" in path or "%" in path:
        raise ValueError("SharePoint Server REST path requires ResourcePath for '#' or '%' names")
    if "\\" in path or "?" in path or any(ord(char) < 32 for char in path):
        raise ValueError("Invalid SharePoint path")
    segments = path.strip("/").split("/")
    if any(segment in ("", ".", "..") for segment in segments):
        raise ValueError("Invalid SharePoint path")
    return segments


def _safe_relative(path):
    if (
        not isinstance(path, str)
        or not path.startswith("/")
        or path != "/" + "/".join(_segments(path))
    ):
        raise ValueError("Invalid SharePoint server-relative path")
    return path


def _inside(path, parent):
    return isinstance(path, str) and path.startswith(parent.rstrip("/") + "/")


def _date(value):
    if not value:
        return datetime(1970, 1, 1, tzinfo=UTC)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid SharePoint modification time") from exc


class SharePointOnPremConnector(BaseConnector):
    """NTLM REST integration for nominated SharePoint Server sites and libraries.

    Does not enumerate a farm, synchronize permissions, or subscribe to changes.
    Documents have owner-only OpenRAG ACLs, not inherited SharePoint ACLs.
    """

    CONNECTOR_TYPE = "sharepoint_onprem"
    CONNECTOR_API_VERSION = 1
    CONNECTOR_KIND = "bucket"
    CONNECTOR_NAME = "SharePoint Server (NTLM)"
    CONNECTOR_DESCRIPTION = "Browse explicitly configured SharePoint Server sites via NTLM"
    CONNECTOR_ICON = "sharepoint"
    SECRET_CONFIG_KEYS = ("username", "password")
    CREDENTIAL_PAIR = ("username", "password")
    BROWSE_CAPABILITY = "hierarchical"
    CONFIG_FIELDS = (
        {"name": "root_url", "label": "Server URL (HTTPS)", "type": "text", "required": True},
        {"name": "username", "label": "Username", "type": "secret", "required": True},
        {"name": "password", "label": "Password", "type": "secret", "required": True},
        {"name": "domain", "label": "NTLM domain", "type": "text", "required": False},
        {
            "name": "site_paths",
            "label": "Site paths (one per line, relative to server URL)",
            "type": "text",
            "required": True,
        },
    )

    @classmethod
    def is_available(cls, manager, user_id=None):
        return True

    def __init__(self, config):
        super().__init__(config or {})
        self._sites = None
        self._server = None
        self._approved_origin = None
        self._ca_bundle = None

    @staticmethod
    def filename_for_index(file_id: str, filename: str) -> str:
        """Keep picker names natural while keying indexed filenames by source ID."""
        stem, extension = os.path.splitext(filename)
        suffix = hashlib.sha256(file_id.encode("utf-8")).hexdigest()[:32]
        return f"{stem}--sp-{suffix}{extension}"

    def _settings(self):
        if self._sites is not None:
            return
        url = self.config.get("root_url")
        if not isinstance(url, str):
            raise ValueError("root_url is required")
        origin = _origin(url)
        approved = os.environ.get("OPENRAG_SHAREPOINT_ALLOWED_ORIGINS", "")
        origins = [part.strip() for part in approved.replace("\n", ",").split(",") if part.strip()]
        if not origins or any(_origin(item) != item.rstrip("/").lower() for item in origins):
            raise ValueError("Operator must configure HTTPS SharePoint allowed origins")
        if origin not in {_origin(item) for item in origins}:
            raise ValueError("SharePoint origin is not operator-approved")
        parts = urlsplit(url)
        if parts.path != unquote(parts.path) or "//" in parts.path:
            raise ValueError("Invalid SharePoint root URL path")
        base = "/" + "/".join(_segments(parts.path)) if parts.path.strip("/") else ""
        paths = self.config.get("site_paths")
        if not isinstance(paths, str) or not paths.strip():
            raise ValueError("At least one explicit site path is required")
        sites = []
        for line in paths.splitlines():
            if not line.strip():
                continue
            site = base + "/" + "/".join(_segments(line.strip()))
            if site not in sites:
                sites.append(site)
        if not sites or len(sites) > 200:
            raise ValueError("Expected 1–200 explicit site paths")
        if not all(
            isinstance(self.config.get(k), str) and self.config[k] for k in ("username", "password")
        ):
            raise ValueError("Username and password are required")
        ca_bundle = os.environ.get("OPENRAG_SHAREPOINT_CA_BUNDLE")
        if ca_bundle is not None:
            if not os.path.isabs(ca_bundle):
                raise ValueError("SharePoint CA bundle path must be absolute")
            if not os.path.isfile(ca_bundle) or not os.access(ca_bundle, os.R_OK):
                raise ValueError("SharePoint CA bundle must be a readable regular file")
        self._ca_bundle = ca_bundle
        self._approved_origin, self._server, self._sites = origin, origin, sites

    def _session(self):
        self._settings()
        session = requests.Session()
        session.trust_env = False  # ignore unapproved proxies and environment credentials
        domain = self.config.get("domain", "")
        if not isinstance(domain, str) or "\\" in domain or "@" in domain:
            raise ValueError("Invalid NTLM domain")
        username = self.config["username"]
        session.auth = HttpNtlmAuth(
            f"{domain}\\{username}" if domain else username, self.config["password"]
        )
        return session

    def _request(self, session, url, *, params=None, limit=_MAX_METADATA_BYTES):
        # The only request gateway: validate each URL (including constructed REST paths).
        if _origin(url) != self._approved_origin:
            raise ValueError("SharePoint request outside approved origin")
        try:
            with session.get(
                url,
                params=params,
                headers={"Accept": "application/json;odata=verbose"},
                timeout=_TIMEOUT,
                stream=True,
                verify=self._ca_bundle or True,
                allow_redirects=False,
            ) as response:
                status = response.status_code
                if status in (401, 403):
                    raise PermissionError("SharePoint denied access")
                if status == 404:
                    raise FileNotFoundError("SharePoint resource not found")
                if status < 200 or status >= 300:
                    raise RuntimeError(f"SharePoint returned HTTP {status}")
                length = response.headers.get("Content-Length")
                if length and int(length) > limit:
                    raise ValueError("SharePoint response exceeds size limit")
                content = bytearray()
                for chunk in response.iter_content(chunk_size=65536):
                    if len(content) + len(chunk) > limit:
                        raise ValueError("SharePoint response exceeds size limit")
                    content.extend(chunk)
                return bytes(content)
        except requests.exceptions.Timeout:
            raise TimeoutError("SharePoint request timed out") from None
        except requests.exceptions.RequestException:
            raise ConnectionError("SharePoint request failed") from None

    def _json(self, session, url, *, params=None):
        try:
            data = json.loads(self._request(session, url, params=params))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid SharePoint REST response") from exc
        result = data.get("d", data) if isinstance(data, dict) else None
        if not isinstance(result, dict):
            raise ValueError("Invalid SharePoint REST response")
        return result

    def _url(self, site, endpoint):
        return self._server + quote(site, safe="/") + "/_api/web/" + endpoint

    def _folder_endpoint(self, path, collection):
        # Escape OData string literals before URL encoding. Never use a browser URL.
        return (
            "GetFolderByServerRelativeUrl('"
            + quote(path.replace("'", "''"), safe="/")
            + "')/"
            + collection
        )

    def _file_endpoint(self, path):
        return "GetFileByServerRelativeUrl('" + quote(path.replace("'", "''"), safe="/") + "')"

    def _page(self, session, site, endpoint, params, continuation=None):
        base_url = self._url(site, endpoint)
        if continuation is not None:
            if (
                not isinstance(continuation, dict)
                or len(continuation) != 1
                or next(iter(continuation)) not in ("$skiptoken", "$skip")
            ):
                raise ValueError("Invalid SharePoint continuation")
            value = next(iter(continuation.values()))
            if not isinstance(value, str) or not value or len(value) > 4096:
                raise ValueError("Invalid SharePoint continuation")
        args = {**params, **(continuation or {})}
        response = self._json(session, base_url, params=args)
        if not isinstance(response, dict) or not isinstance(response.get("results"), list):
            raise ValueError("Invalid SharePoint REST page")
        if len(response["results"]) > int(params["$top"]):
            raise ValueError("SharePoint REST page exceeds requested size")
        next_url = (
            response.get("__next")
            or response.get("@odata.nextLink")
            or response.get("odata.nextLink")
        )
        next_page = None
        if next_url:
            if (
                not isinstance(next_url, str)
                or _origin(next_url, allow_query=True) != self._approved_origin
            ):
                raise ValueError("SharePoint continuation left approved origin")
            parts = urlsplit(next_url)
            if unquote(parts.path) != unquote(urlsplit(base_url).path):
                raise ValueError("SharePoint continuation left scoped endpoint")
            query = parse_qsl(parts.query, keep_blank_values=True)
            if len(query) != len(dict(query)):
                raise ValueError("Invalid SharePoint continuation")
            values = dict(query)
            for key in params:
                if key in values and values.pop(key) != str(params[key]):
                    raise ValueError("SharePoint continuation changed query")
            if len(values) != 1 or next(iter(values)) not in ("$skiptoken", "$skip"):
                raise ValueError("Invalid SharePoint continuation")
            next_page = values
            if next_page == continuation:
                raise ValueError("SharePoint continuation did not advance")
        return response["results"], next_page

    def _libraries(self, session, site):
        endpoint = "lists"
        params = {
            "$select": "Id,Title,Hidden,BaseTemplate,RootFolder/ServerRelativeUrl",
            "$expand": "RootFolder",
            "$filter": "BaseTemplate eq 101 and Hidden eq false",
            "$top": str(_PAGE_SIZE),
        }
        continuation = None
        seen = set()
        roots = {}
        pages = 0
        while True:
            items, continuation = self._page(session, site, endpoint, params, continuation)
            pages += 1
            if pages > 1000:
                raise ValueError("SharePoint library inventory exceeds page limit")
            if continuation:
                marker = tuple(continuation.items())
                if marker in seen:
                    raise ValueError("SharePoint library pagination repeated")
                seen.add(marker)
            for item in items:
                if item.get("Hidden"):
                    continue
                path = item.get("RootFolder", {}).get("ServerRelativeUrl")
                if isinstance(path, str):
                    _safe_relative(path)
                    if _inside(path, site):
                        roots[path] = item.get("Title") or path.rsplit("/", 1)[-1]
            if not continuation:
                return roots
            if len(roots) > 10000:
                raise ValueError("SharePoint library inventory exceeds limit")

    def _decode_id(self, value, *, session=None):
        self._settings()
        data = _untoken(value)
        if not isinstance(data, list) or len(data) not in (2, 3, 4):
            raise ValueError("Invalid SharePoint identifier")
        kind, site, *rest = data
        if not isinstance(site, str) or site not in self._sites:
            raise ValueError("Identifier outside configured SharePoint sites")
        if kind == "s" and rest == []:
            return data
        if not rest or not isinstance(rest[0], str) or not _inside(rest[0], site):
            raise ValueError("Identifier outside configured SharePoint sites")
        library = _safe_relative(rest[0])
        if session is None:
            raise ValueError("Identifier outside configured SharePoint libraries")
        try:
            libraries = self._libraries(session, site)
        except FileNotFoundError:
            # A missing site/listing is not proof that this indexed file
            # disappeared. Only a 404 from the file endpoint authorizes cleanup.
            raise ConnectionError("SharePoint library scope unavailable") from None
        if library not in libraries:
            raise ValueError("Identifier outside configured SharePoint libraries")
        if kind == "l" and len(rest) == 1:
            return data
        if kind not in ("d", "f") or len(rest) != 2 or not _inside(rest[1], library):
            raise ValueError("Identifier outside configured SharePoint libraries")
        _safe_relative(rest[1])
        return data

    def _cursor(self, value, parent):
        if value is None:
            return {"parent": parent, "phase": "folders", "continuation": None}
        data = _untoken(value)
        if (
            not isinstance(data, dict)
            or data.get("parent") != parent
            or data.get("phase") not in ("sites", "libraries", "folders", "files")
            or set(data) != {"parent", "phase", "continuation"}
        ):
            raise ValueError("Invalid SharePoint picker cursor")
        return data

    def _list_children(self, parent_id, cursor, page_size):
        self._settings()
        if (
            not isinstance(page_size, int)
            or isinstance(page_size, bool)
            or not 1 <= page_size <= _PAGE_SIZE
        ):
            raise ValueError("SharePoint page_size must be between 1 and 200")
        with self._session() as session:
            if parent_id is None:
                state = self._cursor(cursor, parent_id)
                if state["phase"] not in ("folders", "sites"):
                    raise ValueError("Invalid SharePoint picker cursor")
                offset = state["continuation"] or 0
                if (
                    not isinstance(offset, int)
                    or isinstance(offset, bool)
                    or not 0 <= offset <= len(self._sites)
                ):
                    raise ValueError("Invalid SharePoint picker cursor")
                items = self._sites[offset : offset + page_size]
                new_offset = offset + len(items)
                return {
                    "nodes": [
                        {
                            "id": _token(["s", site]),
                            "parent_id": None,
                            "kind": "folder",
                            "name": site.rsplit("/", 1)[-1],
                        }
                        for site in items
                    ],
                    "next_cursor": _token(
                        {"parent": None, "phase": "sites", "continuation": new_offset}
                    )
                    if new_offset < len(self._sites)
                    else None,
                }
            identity = self._decode_id(parent_id, session=session)
            kind, site = identity[:2]
            state = self._cursor(cursor, parent_id)
            if kind == "f":
                raise ValueError("Files have no children")
            if kind == "s":
                if state["phase"] not in ("folders", "libraries"):
                    raise ValueError("Invalid SharePoint picker cursor")
                params = {
                    "$select": "Id,Title,Hidden,BaseTemplate,RootFolder/ServerRelativeUrl",
                    "$expand": "RootFolder",
                    "$filter": "BaseTemplate eq 101 and Hidden eq false",
                    "$top": str(page_size),
                }
                entries, continuation = self._page(
                    session, site, "lists", params, state["continuation"]
                )
                nodes = []
                for entry in entries:
                    if entry.get("Hidden"):
                        continue
                    path = entry.get("RootFolder", {}).get("ServerRelativeUrl")
                    if isinstance(path, str):
                        _safe_relative(path)
                        if _inside(path, site):
                            nodes.append(
                                {
                                    "id": _token(["l", site, path]),
                                    "parent_id": parent_id,
                                    "kind": "folder",
                                    "name": entry.get("Title") or path.rsplit("/", 1)[-1],
                                }
                            )
                next_cursor = (
                    _token(
                        {"parent": parent_id, "phase": "libraries", "continuation": continuation}
                    )
                    if continuation
                    else None
                )
                return {"nodes": nodes, "next_cursor": next_cursor}
            library = identity[2]
            parent_path = library if kind == "l" else identity[3]
            if state["phase"] not in ("folders", "files"):
                raise ValueError("Invalid SharePoint picker cursor")
            nodes = []
            phase = state["phase"]
            continuation = state["continuation"]
            while len(nodes) < page_size:
                collection = "Folders" if phase == "folders" else "Files"
                select = (
                    "Name,ServerRelativeUrl,TimeLastModified"
                    if phase == "folders"
                    else "Name,ServerRelativeUrl,Length,TimeLastModified"
                )
                params = {"$select": select, "$top": str(page_size - len(nodes))}
                entries, continuation = self._page(
                    session,
                    site,
                    self._folder_endpoint(parent_path, collection),
                    params,
                    continuation,
                )
                for entry in entries:
                    path = entry.get("ServerRelativeUrl")
                    if isinstance(path, str):
                        _safe_relative(path)
                    if not isinstance(path, str) or path.rsplit("/", 1)[0] != parent_path:
                        continue  # Do not expose an out-of-scope server response.
                    item = {
                        "id": _token(["d" if phase == "folders" else "f", site, library, path]),
                        "parent_id": parent_id,
                        "kind": "folder" if phase == "folders" else "file",
                        "name": entry.get("Name") or path.rsplit("/", 1)[-1],
                    }
                    if entry.get("TimeLastModified"):
                        item["modified_time"] = entry["TimeLastModified"]
                    if phase == "files" and entry.get("Length") is not None:
                        item["size"] = int(entry["Length"])
                    nodes.append(item)
                if continuation:
                    break
                if phase == "files":
                    return {"nodes": nodes, "next_cursor": None}
                phase = "files"
            return {
                "nodes": nodes,
                "next_cursor": _token(
                    {"parent": parent_id, "phase": phase, "continuation": continuation}
                ),
            }

    async def list_children(
        self, parent_id: str | None = None, cursor: str | None = None, page_size: int = 100
    ) -> dict:
        return await asyncio.to_thread(self._list_children, parent_id, cursor, page_size)

    async def authenticate(self):
        def probe():
            self._settings()
            with self._session() as session:
                for site in self._sites:
                    self._json(session, self._url(site, "")[:-1], params={"$select": "Id"})
                    self._libraries(session, site)

        try:
            await asyncio.to_thread(probe)
        except PermissionError:
            self._authenticated = False
            return False
        self._authenticated = True
        return True

    async def list_files(self, page_token=None, max_files=None, **kwargs):
        """Breadth-first inventory; token only contains directories, never unverified files."""
        limit = 200 if max_files is None else max_files
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValueError("max_files must be between 1 and 1000")
        if page_token is None:
            queue = deque([None])
            cursor = None
        else:
            state = _untoken(page_token)
            if (
                not isinstance(state, dict)
                or set(state) != {"queue", "cursor"}
                or not isinstance(state["queue"], list)
                or not state["queue"]
            ):
                raise ValueError("Invalid SharePoint inventory cursor")
            queue, cursor = deque(state["queue"]), state["cursor"]
        files = []
        pages = 0
        while len(files) < limit and queue and pages < 1000:
            result = await self.list_children(queue[0], cursor, min(_PAGE_SIZE, limit - len(files)))
            pages += 1
            for node in result["nodes"]:
                if node["kind"] == "file":
                    files.append(
                        {
                            "id": node["id"],
                            "name": node["name"],
                            "size": node.get("size"),
                            "modified_time": node.get("modified_time"),
                        }
                    )
                else:
                    queue.append(node["id"])
            cursor = result["next_cursor"]
            if cursor is None:
                queue.popleft()
        next_page_token = _token({"queue": list(queue), "cursor": cursor}) if queue else None
        return {"files": files, "next_page_token": next_page_token}

    def _is_definitively_missing(self, file_id):
        self._settings()
        with self._session() as session:
            try:
                kind, site, _, path = self._decode_id(file_id, session=session)
                if kind != "f":
                    return False
                self._json(
                    session,
                    self._url(site, self._file_endpoint(path)),
                    params={"$select": "ServerRelativeUrl"},
                )
                return False  # A successful response, even if malformed, is not a deletion signal.
            except FileNotFoundError:
                # _decode_id converts a missing site/library listing to a scope
                # error. Only a 404 from this specific file endpoint reaches here.
                return True
            except (ValueError, ConnectionError, PermissionError, TimeoutError, RuntimeError):
                return False

    async def is_definitively_missing(self, file_id: str) -> bool:
        return await asyncio.to_thread(self._is_definitively_missing, file_id)

    def _get_file_content(self, file_id):
        self._settings()
        owner = self.config.get("user_id")
        if not isinstance(owner, str) or not owner:
            raise ValueError("OpenRAG connection owner is required for owner-only documents")
        with self._session() as session:
            identity = self._decode_id(file_id, session=session)
            if identity[0] != "f":
                raise ValueError("Only SharePoint file identifiers can be downloaded")
            _, site, library, path = identity
            endpoint = self._file_endpoint(path)
            metadata = self._json(
                session,
                self._url(site, endpoint),
                params={
                    "$select": "Name,ServerRelativeUrl,Length,TimeLastModified,TimeCreated,ETag"
                },
            )
            if not isinstance(metadata, dict) or metadata.get("ServerRelativeUrl") != path:
                raise ValueError("SharePoint file metadata left configured scope")
            if int(metadata.get("Length", -1)) > _MAX_FILE_BYTES:
                raise ValueError("SharePoint file exceeds size limit")
            content = self._request(
                session, self._url(site, endpoint + "/$value"), limit=_MAX_FILE_BYTES
            )
        filename = metadata.get("Name") or path.rsplit("/", 1)[-1]
        modified = _date(metadata.get("TimeLastModified"))
        return ConnectorDocument(
            id=file_id,
            filename=self.filename_for_index(file_id, filename),
            mimetype=mimetypes.guess_type(filename)[0] or "application/octet-stream",
            content=content,
            source_url=self._server + quote(path, safe="/"),
            acl=DocumentACL(owner=owner, allowed_users=[owner]),
            modified_time=modified,
            created_time=_date(metadata.get("TimeCreated"))
            if metadata.get("TimeCreated")
            else modified,
            metadata={
                "size": len(content),
                "site_path": site,
                "library_path": library,
                "content_etag": metadata.get("ETag"),
            },
        )

    async def get_file_content(self, file_id: str) -> ConnectorDocument:
        return await asyncio.to_thread(self._get_file_content, file_id)

    async def setup_subscription(self) -> str:
        return ""  # SharePoint Server REST has no connector-managed subscription.

    async def cleanup_subscription(self, subscription_id: str) -> bool:
        return True

    async def handle_webhook(self, payload: dict) -> list[str]:
        return []
