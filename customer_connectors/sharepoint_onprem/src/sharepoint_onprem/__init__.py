"""SharePoint Server REST connector. Only explicitly configured sites are discoverable.

Requires OPENRAG_SHAREPOINT_ALLOWED_ORIGINS to contain the server's HTTPS origin
(plain HTTP only with OPENRAG_SHAREPOINT_ALLOW_INSECURE_HTTP=true, for test farms).
IDs encode server-relative paths, but are not authorization tokens: every use is
checked against configured sites and the server's document libraries. Reads may
use a library listing confirmed within the last _LIBRARY_CACHE_SECONDS; any
not-found or denied answer, and every deletion check, is re-checked against a
fresh listing, so a cached scope can never turn into a deletion signal.
IDs also carry the approved origin: the same path on another server is a
different file, and an ID from another origin is a scope error, never a
deletion signal.
Nominated site paths must equal the server's ServerRelativeUrl exactly, casing
included: scope checks are exact, so authenticate rejects a mismatch rather
than letting it hide every library.
"""

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import mimetypes
import os
import threading
import time
from datetime import UTC, datetime
from urllib.parse import parse_qsl, quote, unquote, urlsplit

import requests
from requests_ntlm import HttpNtlmAuth

from connectors.base import BaseConnector, ConnectorDocument, DocumentACL

# Stdlib logging is bridged into the host's structlog pipeline. The host drops
# sub-ERROR records from installed packages, so operator-actionable
# configuration errors are logged at ERROR, as are denied access, timeouts and
# connection failures (the host reports the sign-in outcome only as a category).
logger = logging.getLogger(__name__)
_MAX_METADATA_BYTES = 4 * 1024 * 1024
_MAX_FILE_BYTES = 50 * 1024 * 1024
_MAX_TOKEN_BYTES = 256 * 1024
_PAGE_SIZE = 200
# Inventory stack frames (root + site + library + folders). SharePoint's 400-char
# URL limit keeps real trees far shallower; past this a sync fails closed.
_MAX_INVENTORY_DEPTH = 64
_MAX_INVENTORY_REQUESTS = 1000  # list_children pages per list_files call
_TIMEOUT = (5, 20)  # connection, read (seconds)
# Reuse, not trust: see _borrow_session, _scoped_libraries and authenticate.
_LIBRARY_CACHE_SECONDS = 60
_AUTH_CACHE_SECONDS = 300
_SESSION_IDLE_SECONDS = 60
_MAX_IDLE_SESSIONS = 4


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


def _schemes():
    # Plain HTTP exposes NTLM exchanges and document content on the wire; it is an
    # explicit operator opt-in for isolated test farms, never a fallback.
    insecure = os.environ.get("OPENRAG_SHAREPOINT_ALLOW_INSECURE_HTTP", "").strip().lower()
    return ("https", "http") if insecure == "true" else ("https",)


def _origin(url, *, allow_query=False):
    parts = urlsplit(url)
    if (
        parts.scheme not in _schemes()
        or not parts.hostname
        or parts.username
        or parts.password
        or (parts.query and not allow_query)
        or parts.fragment
        or parts.port == 0
    ):
        raise ValueError("SharePoint requires an approved HTTPS origin")
    return f"{parts.scheme}://{parts.netloc.lower()}"


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


def _root_folder_path(entry):
    """A list entry's RootFolder/ServerRelativeUrl; an absent RootFolder is skipped."""
    root = entry.get("RootFolder", {})
    if not isinstance(root, dict):
        raise ValueError("Invalid SharePoint REST response")
    return root.get("ServerRelativeUrl")


def _text(entry, key):
    """A display/metadata field, only when the server sent a non-empty string."""
    value = entry.get(key)
    return value if isinstance(value, str) and value else None


def _size(value):
    """A file Length. odata=verbose serialises Edm.Int64 as a decimal string."""
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError("Invalid SharePoint REST response")
    try:
        size = int(value)
    except ValueError:
        raise ValueError("Invalid SharePoint REST response") from None
    if size < 0:
        raise ValueError("Invalid SharePoint REST response")
    return size


def _date(value):
    if not value:
        return datetime(1970, 1, 1, tzinfo=UTC)
    if not isinstance(value, str):
        raise ValueError("Invalid SharePoint modification time")
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
    # A removed site or a permission-trimmed library also drops files from the
    # listing; only a 404 at the file endpoint proves a deletion.
    REQUIRES_CONFIRMED_DELETION = True
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
        # Connectors are cached per connection and called from asyncio.to_thread
        # workers, so shared state below is guarded by this lock.
        self._lock = threading.Lock()
        self._idle_sessions: list[tuple[requests.Session, float]] = []
        self._library_cache: dict[str, tuple[float, dict[str, str]]] = {}
        self._authenticated_until = 0.0

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
            # "/" nominates the root site collection of root_url.
            relative = line.strip()
            site = base + ("/" + "/".join(_segments(relative)) if relative != "/" else "")
            if site not in sites:
                sites.append(site)
        if not sites or len(sites) > 200:
            raise ValueError("Expected 1–200 explicit site paths")
        if not all(
            isinstance(self.config.get(k), str) and self.config[k] for k in ("username", "password")
        ):
            raise ValueError("Username and password are required")
        # A blank value (compose/.env often export unset variables as "") means
        # unset: verify against the default trust store.
        ca_bundle = os.environ.get("OPENRAG_SHAREPOINT_CA_BUNDLE", "").strip() or None
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

    @contextlib.contextmanager
    def _borrow_session(self):
        """Lend one thread an NTLM-authenticated session from a small pool.

        Reusing a session keeps its keep-alive connections, so the TCP/TLS setup
        and the three-leg NTLM handshake are paid once rather than per call. A
        session serves one thread at a time; concurrent callers get their own.
        A session that saw any failure is closed rather than reused.
        """
        now = time.monotonic()
        session = None
        with self._lock:
            while self._idle_sessions:
                candidate, last_used = self._idle_sessions.pop()
                if now - last_used <= _SESSION_IDLE_SECONDS:
                    session = candidate
                    break
                candidate.close()  # The server has likely dropped it; never retry on it.
        if session is None:
            session = self._session()
        try:
            yield session
        except BaseException:
            session.close()
            raise
        with self._lock:
            self._idle_sessions.append((session, time.monotonic()))
            while len(self._idle_sessions) > _MAX_IDLE_SESSIONS:
                self._idle_sessions.pop(0)[0].close()

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
                    # The header is server-controlled: collapse whitespace and cap it.
                    challenge = " ".join(response.headers.get("WWW-Authenticate", "none").split())[
                        :80
                    ]
                    logger.error(
                        "SharePoint denied access (HTTP %d, authentication challenge: %s). "
                        "Verify the account, its NTLM domain and its permissions on the "
                        "nominated sites.",
                        status,
                        challenge,
                    )
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
        except requests.exceptions.Timeout as exc:
            phase = "connection" if isinstance(exc, requests.exceptions.ConnectTimeout) else "reply"
            # Only the class is logged: the exception text can carry the URL.
            logger.error(
                "SharePoint %s timed out (limits: %ds connect, %ds read). A farm that has "
                "just restarted can be slow on its first requests.",
                phase,
                *_TIMEOUT,
            )
            raise TimeoutError("SharePoint request timed out") from None
        except requests.exceptions.RequestException as exc:
            logger.error(
                "SharePoint request failed (%s). Check the URL, DNS, TLS trust "
                "(OPENRAG_SHAREPOINT_CA_BUNDLE) and firewall.",
                type(exc).__name__,
            )
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
        # Every caller reads entries with .get(): validate the shape once here so a
        # malformed server answer is always this module's ValueError.
        if not all(isinstance(entry, dict) for entry in response["results"]):
            logger.error("Failed to parse SharePoint REST page. Error: non-object entry.")
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
                path = _root_folder_path(item)
                if isinstance(path, str):
                    _safe_relative(path)
                    if _inside(path, site):
                        roots[path] = _text(item, "Title") or path.rsplit("/", 1)[-1]
            if not continuation:
                return roots
            if len(roots) > 10000:
                raise ValueError("SharePoint library inventory exceeds limit")

    def _scoped_libraries(self, session, site, *, fresh=False):
        """Visible document libraries of a site, reusing a recent listing.

        Only a successful listing is cached. Callers that act on a negative
        answer (not found, denied) or authorize deletion pass fresh=True.
        """
        if not fresh:
            with self._lock:
                cached = self._library_cache.get(site)
            if cached is not None and time.monotonic() < cached[0]:
                return cached[1]
        try:
            roots = self._libraries(session, site)
        except Exception:
            with self._lock:
                self._library_cache.pop(site, None)
            raise
        with self._lock:
            self._library_cache[site] = (time.monotonic() + _LIBRARY_CACHE_SECONDS, roots)
        return roots

    def _decode_id(self, value, *, session=None, fresh=False):
        self._settings()
        data = _untoken(value)
        # [kind, origin, site, *scope]: "s" has no scope, "l" adds the library,
        # "d"/"f" add the library and the item path.
        if not isinstance(data, list) or len(data) not in (3, 4, 5):
            raise ValueError("Invalid SharePoint identifier")
        kind, origin, site, *rest = data
        if origin != self._approved_origin:
            # Checked first, before any request: an ID minted for another server
            # (or before IDs carried an origin) must not resolve against this one.
            raise ValueError("Identifier outside the configured SharePoint server")
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
            libraries = self._scoped_libraries(session, site, fresh=fresh)
            if library not in libraries and not fresh:
                # A library created since the cached listing must not be hidden.
                libraries = self._scoped_libraries(session, site, fresh=True)
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
        with self._borrow_session() as session:
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
                            "id": _token(["s", self._approved_origin, site]),
                            "parent_id": None,
                            "kind": "folder",
                            "name": site.rsplit("/", 1)[-1] or "Root site",
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
            kind, site = identity[0], identity[2]
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
                    path = _root_folder_path(entry)
                    if isinstance(path, str):
                        _safe_relative(path)
                        if _inside(path, site):
                            nodes.append(
                                {
                                    "id": _token(["l", self._approved_origin, site, path]),
                                    "parent_id": parent_id,
                                    "kind": "folder",
                                    "name": _text(entry, "Title") or path.rsplit("/", 1)[-1],
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
            library = identity[3]
            parent_path = library if kind == "l" else identity[4]
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
                    if phase == "folders" and path == library + "/Forms":
                        continue  # Library view pages and templates, not documents.
                    item = {
                        "id": _token(
                            [
                                "d" if phase == "folders" else "f",
                                self._approved_origin,
                                site,
                                library,
                                path,
                            ]
                        ),
                        "parent_id": parent_id,
                        "kind": "folder" if phase == "folders" else "file",
                        "name": _text(entry, "Name") or path.rsplit("/", 1)[-1],
                    }
                    modified = _text(entry, "TimeLastModified")
                    if modified:
                        item["modified_time"] = modified
                    if phase == "files" and entry.get("Length") is not None:
                        item["size"] = _size(entry["Length"])
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

    def _verify_site_path(self, session, index, site):
        """Require the nominated path to be exactly the server's site URL.

        SharePoint resolves URLs case-insensitively, but every scope check here
        is an exact comparison against server-reported paths, so a casing
        mismatch would silently filter out every library. casefold() only picks
        the operator hint; it never authorizes anything.
        """
        web = self._json(
            session, self._url(site, "")[:-1], params={"$select": "Id,ServerRelativeUrl"}
        )
        expected = site or "/"  # The root site is "" internally; SharePoint reports "/".
        actual = web.get("ServerRelativeUrl")
        if not isinstance(actual, str):
            logger.error(
                "Failed to verify nominated SharePoint site path %d. "
                "Error: response has no ServerRelativeUrl.",
                index,
            )
            raise ValueError("SharePoint site response is missing ServerRelativeUrl")
        if actual == expected:
            return
        if actual.casefold() == expected.casefold():
            logger.error(
                "Failed to verify nominated SharePoint site path %d. Error: casing differs "
                "from the server (configured %r, server %r); update site_paths to match.",
                index,
                expected,
                actual,
            )
            raise ValueError(f"SharePoint site path casing differs from the server; use {actual!r}")
        logger.error(
            "Failed to verify nominated SharePoint site path %d. Error: not a site URL "
            "(configured %r resolves to site %r).",
            index,
            expected,
            actual,
        )
        raise ValueError("Nominated SharePoint path is not a site URL")

    async def authenticate(self):
        """Probe every nominated site; a success is trusted for _AUTH_CACHE_SECONDS.

        The host re-authenticates its cached instance on every status request,
        which would otherwise fan out to the whole farm. Test/Save build a new
        instance, so they always run the full probe; a failure is never cached.
        """
        if time.monotonic() < self._authenticated_until:
            return True

        try:
            self._settings()
        except ValueError as exc:
            # These messages are static and secret-free; the host reports only a category.
            logger.error("SharePoint connection settings were rejected: %s", exc)
            raise

        def probe():
            with self._borrow_session() as session:
                for index, site in enumerate(self._sites):
                    logger.debug("Verifying nominated SharePoint site path %d...", index)
                    self._verify_site_path(session, index, site)
                    logger.debug("Verified nominated SharePoint site path %d.", index)
                    self._scoped_libraries(session, site, fresh=True)

        try:
            await asyncio.to_thread(probe)
        except PermissionError:
            self._authenticated_until = 0.0
            self._authenticated = False
            return False
        self._authenticated_until = time.monotonic() + _AUTH_CACHE_SECONDS
        self._authenticated = True
        return True

    @staticmethod
    def _inventory_stack(page_token):
        """Decode an inventory token into frames, failing closed on any other shape.

        A frame is one listing position inside an open folder level:
        [parent_id, page_cursor, consumed]. Frame 0 is the root (parent None).
        """
        if page_token is None:
            return [{"parent": None, "cursor": None, "consumed": 0, "page": None}]
        try:
            state = _untoken(page_token)
            stack = state["stack"] if isinstance(state, dict) and set(state) == {"stack"} else None
            if not isinstance(stack, list) or not 1 <= len(stack) <= _MAX_INVENTORY_DEPTH:
                raise ValueError
            frames = []
            for index, frame in enumerate(stack):
                if not isinstance(frame, list) or len(frame) != 3:
                    raise ValueError
                parent, cursor, consumed = frame
                if (parent is None) != (index == 0) or not isinstance(parent, str | None):
                    raise ValueError
                if not isinstance(cursor, str | None) or cursor == "":
                    raise ValueError
                if (
                    not isinstance(consumed, int)
                    or isinstance(consumed, bool)
                    or not 0 <= consumed <= _PAGE_SIZE
                ):
                    raise ValueError
                frames.append(
                    {"parent": parent, "cursor": cursor, "consumed": consumed, "page": None}
                )
            return frames
        except ValueError:
            logger.error("Failed to resume SharePoint inventory. Error: invalid inventory cursor.")
            raise ValueError("Invalid SharePoint inventory cursor") from None

    async def list_files(self, page_token=None, max_files=None, **kwargs):
        """Depth-first inventory over list_children, resumable in O(depth) state.

        The token holds one listing position per open folder level, never a
        frontier of pending folders, so it stays small however wide a library
        is. Every node still comes from list_children, so IDs and continuations
        pass the same scope checks as the picker. Pages are always requested at
        _PAGE_SIZE so a (parent, cursor) pair re-lists the same page on resume.
        If a folder changes between calls, an offset resume can repeat or skip
        one entry: repeats are de-duplicated downstream, a skip waits for the
        next sync, and a missing listing never signals deletion.
        """
        limit = 200 if max_files is None else max_files
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValueError("max_files must be between 1 and 1000")
        stack = self._inventory_stack(page_token)
        logger.debug("Listing SharePoint inventory page (resume depth %d)...", len(stack))
        files = []
        requests_made = 0
        # Each iteration consumes a node, advances a page or pops a frame, and a
        # call always makes at least one request, so host loops that follow
        # next_page_token until it is None always terminate.
        while stack and len(files) < limit:
            frame = stack[-1]
            if frame["page"] is None:
                if requests_made >= _MAX_INVENTORY_REQUESTS:
                    break
                frame["page"] = await self.list_children(
                    frame["parent"], frame["cursor"], _PAGE_SIZE
                )
                requests_made += 1
            nodes = frame["page"]["nodes"]
            if frame["consumed"] >= len(nodes):  # Exhausted, or the listing shrank.
                next_cursor = frame["page"]["next_cursor"]
                if next_cursor:
                    frame.update(cursor=next_cursor, consumed=0, page=None)
                else:
                    stack.pop()
                continue
            node = nodes[frame["consumed"]]
            frame["consumed"] += 1
            if node["kind"] == "file":
                files.append(
                    {
                        "id": node["id"],
                        "name": node["name"],
                        "size": node.get("size"),
                        "modified_time": node.get("modified_time"),
                    }
                )
                continue
            if len(stack) >= _MAX_INVENTORY_DEPTH:
                logger.error(
                    "Failed to list SharePoint inventory. Error: folder nesting exceeds %d levels.",
                    _MAX_INVENTORY_DEPTH,
                )
                raise ValueError("SharePoint folder depth exceeds inventory limit")
            stack.append({"parent": node["id"], "cursor": None, "consumed": 0, "page": None})
        next_page_token = None
        if stack:
            try:
                next_page_token = _token(
                    {"stack": [[f["parent"], f["cursor"], f["consumed"]] for f in stack]}
                )
            except ValueError as error:
                logger.error(
                    "Failed to encode SharePoint inventory cursor at depth %d. Error: %s.",
                    len(stack),
                    error,
                )
                raise
        logger.debug(
            "Listed SharePoint inventory page: %d files, %d requests, depth %d, token %d bytes.",
            len(files),
            requests_made,
            len(stack),
            len(next_page_token or ""),
        )
        return {"files": files, "next_page_token": next_page_token}

    def _is_definitively_missing(self, file_id):
        self._settings()
        with self._borrow_session() as session:
            try:
                # Authorizes chunk deletion: never trust a cached library scope.
                identity = self._decode_id(file_id, session=session, fresh=True)
                if identity[0] != "f":
                    return False
                _, _, site, _, path = identity
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
        with self._borrow_session() as session:
            identity = self._decode_id(file_id, session=session)
            if identity[0] != "f":
                raise ValueError("Only SharePoint file identifiers can be downloaded")
            _, _, site, library, path = identity
            endpoint = self._file_endpoint(path)
            try:
                metadata = self._json(
                    session,
                    self._url(site, endpoint),
                    params={
                        "$select": "Name,ServerRelativeUrl,Length,TimeLastModified,TimeCreated,ETag"
                    },
                )
                if not isinstance(metadata, dict) or metadata.get("ServerRelativeUrl") != path:
                    raise ValueError("SharePoint file metadata left configured scope")
                length = metadata.get("Length")
                if length is not None and _size(length) > _MAX_FILE_BYTES:
                    raise ValueError("SharePoint file exceeds size limit")
                content = self._request(
                    session, self._url(site, endpoint + "/$value"), limit=_MAX_FILE_BYTES
                )
            except (FileNotFoundError, PermissionError):
                # FileNotFoundError deletes indexed chunks. The scope above may
                # come from a cached listing, so confirm it is still current: a
                # vanished library or listing raises a non-deletion error instead.
                self._decode_id(file_id, session=session, fresh=True)
                raise
        filename = _text(metadata, "Name") or path.rsplit("/", 1)[-1]
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
                "content_etag": _text(metadata, "ETag"),
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
