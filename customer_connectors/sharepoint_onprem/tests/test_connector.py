"""Public-interface tests against a stateful SharePoint REST transport."""

import asyncio
import base64
import io
import json
from contextlib import ExitStack
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

import pytest
import requests
import sharepoint_onprem
from requests_ntlm import HttpNtlmAuth
from sharepoint_onprem import SharePointOnPremConnector

ORIGIN = "https://sharepoint.example.test"
SITE = "/sites/alpha"
LIBRARY = SITE + "/Docs"
NESTED = LIBRARY + "/team/nested"


def wide_folder(n):
    # Long names give IDs a realistic size (~200 B), as deep farm paths do.
    return f"{LIBRARY}/w-{'x' * 60}-{n:05d}"


def run(awaitable):
    return asyncio.run(awaitable)


def altered_file_id(file_id, *, library, path):
    decoded = json.loads(base64.urlsafe_b64decode(file_id + "=" * (-len(file_id) % 4)))
    decoded[3:] = [library, path]  # [kind, origin, site, library, path]
    return (
        base64.urlsafe_b64encode(json.dumps(decoded, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )


class SharePointServer:
    def __init__(self):
        self.calls = []
        self.count = 537
        self.next_origin = ORIGIN
        self.status = {}
        self.weird_path = None
        self.blocked_site = None
        self.file_modified = "2024-03-01T00:00:00Z"
        self.duplicate_folder = False
        self.ca_bundle = None
        self.library_visible = True
        self.sessions = []
        # Requested site path -> ServerRelativeUrl the web probe reports
        # (default: the path itself; None omits the field).
        self.web_urls = {}
        # Empty sibling folders under the library; every 500th holds one file.
        self.wide_folders = 0
        self.root_file = False

    def lists_calls(self):
        return sum("/_api/web/lists" in url for url in self.calls)

    def get(self, session, url, *, params, **options):
        assert isinstance(session.auth, HttpNtlmAuth)
        if session not in self.sessions:
            self.sessions.append(session)
        assert options == {
            "headers": {"Accept": "application/json;odata=verbose"},
            "timeout": (5, 20),
            "stream": True,
            "verify": self.ca_bundle or True,
            "allow_redirects": False,
        }
        prepared = requests.Request("GET", url, params=params).prepare().url
        self.calls.append(prepared)
        parts = urlsplit(prepared)
        assert f"{parts.scheme}://{parts.netloc}" == ORIGIN
        assert parts.path.startswith(SITE + "/_api/") or parts.path.startswith("/sites/beta/_api/")
        endpoint = unquote(parts.path.split("/_api/web", 1)[1]).removeprefix("/")
        query = parse_qs(parts.query)
        if self.blocked_site and parts.path.startswith(self.blocked_site + "/_api/"):
            return self.response(403, {})
        if self.status.get(endpoint) == "timeout":
            raise requests.exceptions.Timeout("secret password MUST NOT escape")
        if self.status.get(endpoint):
            return self.response(self.status[endpoint], {})
        if endpoint == "":
            site_path = parts.path.split("/_api/", 1)[0]
            web = {"Id": "site"}
            reported = self.web_urls.get(site_path, site_path or "/")
            if reported is not None:
                web["ServerRelativeUrl"] = reported
            return self.response(200, {"d": web})
        if endpoint == "lists":
            items = (
                [
                    {
                        "Title": "Documents",
                        "Hidden": False,
                        "RootFolder": {"ServerRelativeUrl": LIBRARY},
                    },
                    {
                        "Title": "Hidden",
                        "Hidden": True,
                        "RootFolder": {"ServerRelativeUrl": SITE + "/Hidden"},
                    },
                ]
                if parts.path.startswith(SITE) and self.library_visible
                else []
            )
        elif endpoint.startswith("GetFolderByServerRelativeUrl('"):
            folder, collection = endpoint.removeprefix("GetFolderByServerRelativeUrl('").split(
                "')/", 1
            )
            folder = folder.replace("''", "'")
            if folder == LIBRARY and collection == "Folders":
                # SharePoint lists the library's view pages/templates folder first.
                items = [
                    {"Name": "Forms", "ServerRelativeUrl": LIBRARY + "/Forms"},
                    {"Name": "team", "ServerRelativeUrl": LIBRARY + "/team"},
                ]
                if self.duplicate_folder:
                    items.append({"Name": "other", "ServerRelativeUrl": LIBRARY + "/other"})
                items += [
                    {"Name": wide_folder(n).rsplit("/", 1)[-1], "ServerRelativeUrl": wide_folder(n)}
                    for n in range(self.wide_folders)
                ]
            elif folder == LIBRARY and collection == "Files" and self.root_file:
                items = [{"Name": "root.txt", "ServerRelativeUrl": LIBRARY + "/root.txt"}]
            elif folder.startswith(LIBRARY + "/w-") and self.wide_folders:
                n = int(folder.rsplit("-", 1)[-1])
                items = (
                    [{"Name": f"wide-{n}.txt", "ServerRelativeUrl": f"{folder}/wide-{n}.txt"}]
                    if collection == "Files" and n % 500 == 0
                    else []
                )
            elif folder == LIBRARY + "/team" and collection == "Folders":
                items = [{"Name": "nested", "ServerRelativeUrl": NESTED}]
            elif folder == NESTED and collection == "Files":
                items = (
                    [
                        {
                            "Name": self.weird_path.rsplit("/", 1)[-1],
                            "ServerRelativeUrl": self.weird_path,
                        }
                    ]
                    if self.weird_path
                    else [
                        {
                            "Name": f"doc-{n}.txt",
                            "ServerRelativeUrl": f"{NESTED}/doc-{n}.txt",
                            "Length": 9,
                            "TimeLastModified": "2024-03-01T00:00:00Z",
                        }
                        for n in range(self.count)
                    ]
                )
            elif folder == LIBRARY + "/other" and collection == "Files" and self.duplicate_folder:
                items = [
                    {
                        "Name": "doc-0.txt",
                        "ServerRelativeUrl": LIBRARY + "/other/doc-0.txt",
                        "Length": 9,
                        "TimeLastModified": "2024-03-01T00:00:00Z",
                    }
                ]
            elif folder in (LIBRARY, LIBRARY + "/team", LIBRARY + "/other", NESTED):
                items = []
            else:
                return self.response(404, {})
        elif endpoint.startswith("GetFileByServerRelativeUrl('"):
            location = endpoint.removeprefix("GetFileByServerRelativeUrl('").split("')", 1)[0]
            if location == LIBRARY + "/other/doc-0.txt" and self.duplicate_folder:
                index = 0
            elif location.startswith(NESTED + "/doc-") and location.endswith(".txt"):
                try:
                    index = int(location.removeprefix(NESTED + "/doc-").removesuffix(".txt"))
                except ValueError:
                    return self.response(404, {})
            else:
                return self.response(404, {})
            if index >= self.count:
                return self.response(404, {})
            if endpoint.endswith("/$value"):
                return self.response(200, f"document {index}".encode())
            return self.response(
                200,
                {
                    "d": {
                        "Name": f"doc-{index}.txt",
                        "ServerRelativeUrl": location,
                        "Length": 9,
                        "TimeCreated": "2024-02-01T00:00:00Z",
                        "TimeLastModified": self.file_modified,
                        "ETag": '"version-1"',
                    }
                },
            )
        else:
            return self.response(404, {})
        offset = int(query.get("$skiptoken", ["0"])[0])
        size = min(int(query.get("$top", ["200"])[0]), 73)  # Server pages independently of the UI.
        page = items[offset : offset + size]
        data = {"results": page}
        if offset + size < len(items):
            q = {key: value[0] for key, value in query.items() if key != "$skiptoken"}
            q["$skiptoken"] = str(offset + size)
            data["__next"] = f"{self.next_origin}{parts.path}?{urlencode(q)}"
        return self.response(200, {"d": data})

    @staticmethod
    def response(status, payload):
        result = requests.Response()
        result.status_code = status
        content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        result.headers["Content-Length"] = str(len(content))
        result.raw = io.BytesIO(content)
        return result


@pytest.fixture
def connector(monkeypatch):
    server = SharePointServer()
    monkeypatch.setenv("OPENRAG_SHAREPOINT_ALLOWED_ORIGINS", ORIGIN)
    monkeypatch.setattr(
        requests.Session, "get", lambda session, url, **kw: server.get(session, url, **kw)
    )
    adapter = SharePointOnPremConnector(
        {
            "root_url": ORIGIN,
            "username": "casey",
            "password": "dont-log-me",
            "domain": "CORP",
            "site_paths": "sites/alpha\nsites/beta",
            "user_id": "owner-123",
        }
    )
    return adapter, server


def navigate(adapter):
    sites = run(adapter.list_children(None, None, 1))
    assert sites["nodes"][0]["name"] == "alpha"
    assert run(adapter.list_children(None, sites["next_cursor"], 1))["nodes"][0]["name"] == "beta"
    site = sites["nodes"][0]
    library = run(adapter.list_children(site["id"]))["nodes"][0]
    folder = run(adapter.list_children(library["id"]))["nodes"][0]
    nested = run(adapter.list_children(folder["id"]))["nodes"][0]
    return library, nested


def test_navigation_inventory_and_owner_scoped_download(connector):
    adapter, server = connector
    assert run(adapter.authenticate()) is True
    library, nested = navigate(adapter)
    assert library["name"] == "Documents"
    assert (
        len(run(adapter.list_children(run(adapter.list_children())["nodes"][0]["id"]))["nodes"])
        == 1
    )
    assert nested["parent_id"] is not None
    names = []
    cursor = None
    while True:
        page = run(adapter.list_children(nested["id"], cursor, 67))
        names.extend(node["name"] for node in page["nodes"])
        assert all(
            node["kind"] == "file" and node["parent_id"] == nested["id"] for node in page["nodes"]
        )
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(names) == len(set(names)) == 537
    inventory = []
    token = None
    while True:
        result = run(adapter.list_files(page_token=token, max_files=99))
        inventory.extend(result["files"])
        token = result["next_page_token"]
        if token is None:
            break
    assert len(inventory) == len({entry["id"] for entry in inventory})
    assert set(entry["name"] for entry in inventory) == set(names)
    selected = next(entry for entry in inventory if entry["name"] == "doc-536.txt")
    document = run(adapter.get_file_content(selected["id"]))
    assert document.content == b"document 536"
    assert document.acl.owner == "owner-123"
    assert document.acl.allowed_users == ["owner-123"]
    assert document.acl.allowed_groups == []
    assert document.modified_time.isoformat() == "2024-03-01T00:00:00+00:00"
    assert document.source_url == ORIGIN + NESTED + "/doc-536.txt"
    assert server.calls[-1].endswith("/$value")


def test_untrusted_ids_and_continuation_cannot_leave_configured_scope(connector):
    adapter, server = connector
    _, nested = navigate(adapter)
    page = run(adapter.list_children(nested["id"], None, 1))
    file_id = page["nodes"][0]["id"]
    with pytest.raises(ValueError, match="configured SharePoint"):
        run(
            adapter.get_file_content(
                altered_file_id(
                    file_id, library="/sites/other/Docs", path="/sites/other/Docs/secret.txt"
                )
            )
        )
    with pytest.raises(ValueError, match="configured SharePoint libraries"):
        run(
            adapter.get_file_content(
                altered_file_id(file_id, library=LIBRARY, path=SITE + "/AnotherLibrary/secret.txt")
            )
        )
    with pytest.raises(ValueError, match="picker cursor"):
        run(adapter.list_children(None, page["next_cursor"], 1))
    server.next_origin = "https://attacker.example"
    with pytest.raises(ValueError, match="approved origin"):
        run(adapter.list_children(nested["id"], None, 1))
    assert all(urlsplit(url).netloc == "sharepoint.example.test" for url in server.calls)


def test_download_not_found_denied_timeout_and_redirect_are_distinct(connector):
    adapter, server = connector
    _, nested = navigate(adapter)
    file_id = run(adapter.list_children(nested["id"], None, 1))["nodes"][0]["id"]
    path = "GetFileByServerRelativeUrl('" + NESTED + "/doc-0.txt')/$value"
    server.status[path] = 404
    with pytest.raises(FileNotFoundError):
        run(adapter.get_file_content(file_id))
    server.status[path] = 403
    with pytest.raises(PermissionError):
        run(adapter.get_file_content(file_id))
    server.status[path] = "timeout"
    with pytest.raises(TimeoutError, match="timed out") as error:
        run(adapter.get_file_content(file_id))
    assert "dont-log-me" not in str(error.value)
    server.status[path] = 302
    with pytest.raises(RuntimeError, match="HTTP 302"):
        run(adapter.get_file_content(file_id))


def test_operator_allowlist_and_response_limits(connector, monkeypatch):
    adapter, server = connector
    monkeypatch.delenv("OPENRAG_SHAREPOINT_ALLOWED_ORIGINS")
    with pytest.raises(ValueError, match="Operator"):
        run(adapter.authenticate())
    monkeypatch.setenv("OPENRAG_SHAREPOINT_ALLOWED_ORIGINS", ORIGIN)
    adapter = SharePointOnPremConnector(
        {**adapter.config, "root_url": "http://sharepoint.example.test"}
    )
    with pytest.raises(ValueError, match="HTTPS"):
        run(adapter.authenticate())
    adapter = SharePointOnPremConnector({**adapter.config, "root_url": ORIGIN})
    _, nested = navigate(adapter)
    file_id = run(adapter.list_children(nested["id"], None, 1))["nodes"][0]["id"]
    original = server.response

    def oversized(status, payload):
        result = original(status, payload)
        if isinstance(payload, bytes):
            result.headers["Content-Length"] = str(60 * 1024 * 1024)
        return result

    server.response = oversized
    with pytest.raises(ValueError, match="size limit"):
        run(adapter.get_file_content(file_id))


def test_plain_http_root_site_requires_explicit_insecure_opt_in(monkeypatch):
    origin = "http://sharepoint.example.test"
    requested = []

    def get(session, url, *, params, **options):
        requested.append(urlsplit(url).path)
        if url == origin + "/_api/web/lists":
            library = {
                "Title": "Docs",
                "Hidden": False,
                "RootFolder": {"ServerRelativeUrl": "/Docs"},
            }
            payload = {"d": {"results": [library]}}
        else:
            payload = {"d": {"Id": "root", "ServerRelativeUrl": "/"}}
        return SharePointServer.response(200, payload)

    monkeypatch.setattr(requests.Session, "get", get)
    monkeypatch.setenv("OPENRAG_SHAREPOINT_ALLOWED_ORIGINS", origin)
    config = {"root_url": origin, "username": "u", "password": "p", "site_paths": "/"}
    with pytest.raises(ValueError, match="HTTPS"):
        run(SharePointOnPremConnector(config).authenticate())
    assert requested == []
    monkeypatch.setenv("OPENRAG_SHAREPOINT_ALLOW_INSECURE_HTTP", "true")
    adapter = SharePointOnPremConnector(config)
    assert run(adapter.authenticate()) is True
    site = run(adapter.list_children())["nodes"]
    assert [node["name"] for node in site] == ["Root site"]
    libraries = run(adapter.list_children(site[0]["id"]))["nodes"]
    assert [node["name"] for node in libraries] == ["Docs"]
    assert requested[0] == "/_api/web"


def test_explicit_operator_ca_bundle_is_used_without_environment_proxies(
    connector, monkeypatch, tmp_path
):
    adapter, server = connector
    ca_bundle = tmp_path / "sharepoint-ca.pem"
    ca_bundle.write_text("operator-provided PEM bundle")
    monkeypatch.setenv("OPENRAG_SHAREPOINT_CA_BUNDLE", str(ca_bundle))
    server.ca_bundle = str(ca_bundle)
    fresh = SharePointOnPremConnector(adapter.config)
    assert run(fresh.authenticate()) is True
    assert fresh._session().trust_env is False

    monkeypatch.setenv("OPENRAG_SHAREPOINT_CA_BUNDLE", "relative.pem")
    with pytest.raises(ValueError, match="absolute"):
        run(SharePointOnPremConnector(adapter.config).authenticate())
    monkeypatch.setenv("OPENRAG_SHAREPOINT_CA_BUNDLE", str(tmp_path))
    with pytest.raises(ValueError, match="regular file"):
        run(SharePointOnPremConnector(adapter.config).authenticate())


@pytest.mark.parametrize("unset", ["", "   "])
def test_blank_ca_bundle_means_unset_and_uses_default_trust(connector, monkeypatch, unset):
    # Compose and .env files commonly export an unset variable as empty.
    adapter, server = connector
    monkeypatch.setenv("OPENRAG_SHAREPOINT_CA_BUNDLE", unset)
    fresh = SharePointOnPremConnector(adapter.config)
    assert run(fresh.authenticate()) is True
    assert fresh._ca_bundle is None  # requests are verified with verify=True


def test_legacy_rest_refuses_ambiguous_resource_path_names(connector):
    adapter, server = connector
    _, nested = navigate(adapter)
    for name in ("budget#2024.txt", "percent%20literal.txt"):
        server.weird_path = NESTED + "/" + name
        with pytest.raises(ValueError, match="ResourcePath"):
            run(adapter.list_children(nested["id"]))
    for site in ("sites/alpha#external", "sites/alpha%25"):
        invalid = SharePointOnPremConnector({**adapter.config, "site_paths": site})
        with pytest.raises(ValueError, match="ResourcePath"):
            run(invalid.authenticate())


def test_document_cannot_download_without_trusted_owner(connector):
    adapter, server = connector
    _, nested = navigate(adapter)
    file_id = run(adapter.list_children(nested["id"], None, 1))["nodes"][0]["id"]
    missing_owner = SharePointOnPremConnector(
        {key: value for key, value in adapter.config.items() if key != "user_id"}
    )
    before = len(server.calls)
    with pytest.raises(ValueError, match="owner"):
        run(missing_owner.get_file_content(file_id))
    assert len(server.calls) == before


def test_authentication_checks_every_nominated_site(connector):
    adapter, server = connector
    server.blocked_site = "/sites/beta"
    assert run(adapter.authenticate()) is False
    assert adapter.is_authenticated is False
    assert any("/sites/beta/_api/web" in url for url in server.calls)


# Review r4540370401: SharePoint resolves URLs case-insensitively but scope
# checks are exact, so a casing mismatch would hide every library behind a
# successful Test. Authentication must reject it and log the server's path.


def test_site_path_casing_mismatch_fails_authentication_with_hint(connector, caplog):
    adapter, server = connector
    server.web_urls[SITE] = "/sites/Alpha"
    with caplog.at_level("ERROR", logger="sharepoint_onprem"):
        with pytest.raises(ValueError, match=r"casing.*'/sites/Alpha'"):
            run(adapter.authenticate())
    assert adapter.is_authenticated is False
    assert server.lists_calls() == 0  # rejected before any library listing
    messages = [record.getMessage() for record in caplog.records]
    assert any("'/sites/alpha'" in m and "'/sites/Alpha'" in m for m in messages)
    assert all(record.levelname == "ERROR" for record in caplog.records)
    assert not any("dont-log-me" in m for m in messages)

    # A failure is never cached: once the server agrees, the next probe passes.
    del server.web_urls[SITE]
    assert run(adapter.authenticate()) is True
    assert server.lists_calls() > 0


def test_nominated_non_site_path_is_rejected(connector, caplog):
    adapter, server = connector
    # A library or folder path resolves to its containing web.
    server.web_urls[SITE] = "/sites"
    with caplog.at_level("ERROR", logger="sharepoint_onprem"):
        with pytest.raises(ValueError, match="not a site URL"):
            run(adapter.authenticate())
    assert any("not a site URL" in record.getMessage() for record in caplog.records)
    assert server.lists_calls() == 0


def test_site_response_without_server_relative_url_fails_closed(connector):
    adapter, server = connector
    server.web_urls["/sites/beta"] = None
    with pytest.raises(ValueError, match="missing ServerRelativeUrl"):
        run(adapter.authenticate())
    assert adapter.is_authenticated is False


# Review r4540370415: the inventory token must not grow with library breadth.
# A breadth-first queue of folder IDs overflowed _MAX_TOKEN_BYTES at ~1-2k
# folders and failed every whole-library sync.


def full_inventory(adapter, max_files, tokens=None):
    inventory, token = [], None
    for _ in range(10_000):  # Host loops have no guard; a stuck cursor must fail here.
        result = run(adapter.list_files(page_token=token, max_files=max_files))
        inventory.extend(result["files"])
        token = result["next_page_token"]
        if tokens is not None and token is not None:
            tokens.append(token)
        if token is None:
            return inventory
    raise AssertionError("inventory did not terminate")


NESTED_DOCS = {f"doc-{n}.txt" for n in range(537)}


def test_inventory_token_stays_bounded_for_wide_libraries(connector):
    adapter, server = connector
    server.wide_folders = 2500
    server.root_file = True
    tokens = []
    inventory = full_inventory(adapter, None, tokens)
    assert tokens and max(len(token) for token in tokens) < 8 * 1024
    assert len(inventory) == len({entry["id"] for entry in inventory})
    expected = NESTED_DOCS | {"root.txt"} | {f"wide-{n}.txt" for n in range(0, 2500, 500)}
    assert {entry["name"] for entry in inventory} == expected


def test_inventory_resumes_mid_page_without_gaps_or_duplicates(connector):
    adapter, server = connector
    inventory = full_inventory(adapter, 7)
    assert len(inventory) == len({entry["id"] for entry in inventory}) == 537
    assert {entry["name"] for entry in inventory} == NESTED_DOCS


def test_inventory_request_budget_still_makes_progress(connector, monkeypatch):
    adapter, server = connector
    monkeypatch.setattr(sharepoint_onprem, "_MAX_INVENTORY_REQUESTS", 1)
    inventory = full_inventory(adapter, 1000)
    assert {entry["name"] for entry in inventory} == NESTED_DOCS


def test_inventory_depth_limit_fails_closed(connector, monkeypatch, caplog):
    adapter, server = connector
    # root + site + library fill three frames; the library's first folder exceeds it.
    monkeypatch.setattr(sharepoint_onprem, "_MAX_INVENTORY_DEPTH", 3)
    with caplog.at_level("ERROR", logger="sharepoint_onprem"):
        with pytest.raises(ValueError, match="depth"):
            run(adapter.list_files())
    assert any("nesting exceeds 3 levels" in record.getMessage() for record in caplog.records)


_ROOT = [None, None, 0]


@pytest.mark.parametrize(
    "state",
    [
        {"queue": [None], "cursor": None},  # the former breadth-first shape
        {"stack": []},
        {"stack": [["forged", None, 0]]},  # root frame must have no parent
        {"stack": [_ROOT, [None, None, 0]]},  # only the root frame may lack a parent
        {"stack": [[None, None, True]]},
        {"stack": [[None, None, -1]]},
        {"stack": [[None, None, 201]]},
        {"stack": [[None, "", 0]]},
        {"stack": [[None, None]]},
        {"stack": [_ROOT], "extra": 1},
        {"stack": [_ROOT] + [["x", None, 0]] * 64},  # deeper than _MAX_INVENTORY_DEPTH
        ["stack"],
    ],
)
def test_inventory_rejects_malformed_or_legacy_cursors(connector, state):
    adapter, server = connector
    with pytest.raises(ValueError, match="inventory cursor"):
        run(adapter.list_files(page_token=sharepoint_onprem._token(state)))
    assert server.calls == []  # rejected before any request


def test_inventory_cursor_cannot_name_an_out_of_scope_parent(connector):
    adapter, server = connector
    forged = sharepoint_onprem._token({"stack": [_ROOT, ["not-an-id", None, 0]]})
    with pytest.raises(ValueError, match="Invalid SharePoint identifier"):
        run(adapter.list_files(page_token=forged))
    with pytest.raises(ValueError, match="inventory cursor"):
        run(adapter.list_files(page_token="not-a-token"))


def test_missing_library_inventory_cannot_signal_file_deletion(connector):
    adapter, server = connector
    _, nested = navigate(adapter)
    file_id = run(adapter.list_children(nested["id"], None, 1))["nodes"][0]["id"]
    server.status["lists"] = 404
    # Cold scope: a new instance has no cached library listing.
    with pytest.raises(ConnectionError, match="scope unavailable"):
        run(SharePointOnPremConnector(adapter.config).get_file_content(file_id))
    # Warm scope: the cached listing may be stale, so a file 404 is re-checked
    # against a fresh listing, whose failure must not read as a deletion.
    server.status["GetFileByServerRelativeUrl('" + NESTED + "/doc-0.txt')"] = 404
    with pytest.raises(ConnectionError, match="scope unavailable"):
        run(adapter.get_file_content(file_id))


def test_missing_remote_modified_time_uses_stable_fallback(connector):
    adapter, server = connector
    _, nested = navigate(adapter)
    file_id = run(adapter.list_children(nested["id"], None, 1))["nodes"][0]["id"]
    server.file_modified = None
    first = run(adapter.get_file_content(file_id))
    second = run(adapter.get_file_content(file_id))
    assert first.modified_time == second.modified_time
    assert first.modified_time.isoformat() == "1970-01-01T00:00:00+00:00"


def test_same_basename_in_distinct_folders_keeps_picker_names_and_indexes_distinct(connector):
    adapter, server = connector
    server.duplicate_folder = True
    site = run(adapter.list_children())["nodes"][0]
    library = run(adapter.list_children(site["id"]))["nodes"][0]
    folders = run(adapter.list_children(library["id"]))["nodes"]
    other = next(folder for folder in folders if folder["name"] == "other")
    nested = run(
        adapter.list_children(next(folder for folder in folders if folder["name"] == "team")["id"])
    )["nodes"][0]
    first = run(adapter.list_children(nested["id"], page_size=1))["nodes"][0]
    second = run(adapter.list_children(other["id"]))["nodes"][0]
    assert first["name"] == second["name"] == "doc-0.txt"
    assert first["id"] != second["id"]
    documents = [run(adapter.get_file_content(node["id"])) for node in (first, second)]
    assert documents[0].id != documents[1].id
    assert documents[0].filename != documents[1].filename
    assert all(
        doc.filename.endswith(".txt") and doc.filename.startswith("doc-0") for doc in documents
    )


def test_declares_confirmed_deletion_so_host_consults_is_definitively_missing():
    # Without the flag the host treats absence from the listing as deletion.
    assert SharePointOnPremConnector.REQUIRES_CONFIRMED_DELETION is True


def test_definitive_file_missing_only_with_visible_site_and_library(connector):
    adapter, server = connector
    _, nested = navigate(adapter)
    file_id = run(adapter.list_children(nested["id"], page_size=1))["nodes"][0]["id"]
    assert run(adapter.is_definitively_missing(file_id)) is False
    server.count = 0
    assert run(adapter.is_definitively_missing(file_id)) is True
    server.count = 537
    server.status["lists"] = 404
    assert run(adapter.is_definitively_missing(file_id)) is False
    server.status.clear()
    server.library_visible = False
    assert run(adapter.is_definitively_missing(file_id)) is False
    server.library_visible = True
    reduced_scope = SharePointOnPremConnector({**adapter.config, "site_paths": "sites/beta"})
    assert run(reduced_scope.is_definitively_missing(file_id)) is False


# Review 1g: reuse sessions and library listings without trusting them for
# anything that could delete indexed content.


class _Clock:
    def __init__(self, monkeypatch):
        self.now = 1000.0
        monkeypatch.setattr(sharepoint_onprem.time, "monotonic", lambda: self.now)


def _first_file_id(adapter):
    _, nested = navigate(adapter)
    return run(adapter.list_children(nested["id"], None, 1))["nodes"][0]["id"]


def test_library_listing_is_reused_for_downloads_until_it_expires(connector, monkeypatch):
    adapter, server = connector
    clock = _Clock(monkeypatch)
    file_id = _first_file_id(adapter)
    before = server.lists_calls()
    for _ in range(3):
        run(adapter.get_file_content(file_id))
    assert server.lists_calls() == before
    clock.now += sharepoint_onprem._LIBRARY_CACHE_SECONDS + 1
    run(adapter.get_file_content(file_id))
    assert server.lists_calls() == before + 1


def test_not_found_under_a_cached_scope_is_rechecked_before_signalling_deletion(connector):
    adapter, server = connector
    file_id = _first_file_id(adapter)
    server.status["GetFileByServerRelativeUrl('" + NESTED + "/doc-0.txt')"] = 404
    before = server.lists_calls()
    with pytest.raises(FileNotFoundError):
        run(adapter.get_file_content(file_id))
    assert server.lists_calls() == before + 1  # exactly one fresh scope check
    server.library_visible = False
    with pytest.raises(ValueError, match="configured SharePoint libraries"):
        run(adapter.get_file_content(file_id))


def test_library_missing_from_cached_listing_is_refetched_not_rejected(connector):
    adapter, server = connector
    file_id = _first_file_id(adapter)
    server.library_visible = False
    with pytest.raises(ValueError, match="configured SharePoint libraries"):
        run(SharePointOnPremConnector(adapter.config).get_file_content(file_id))
    fresh = SharePointOnPremConnector(adapter.config)
    with pytest.raises(ValueError):
        run(fresh.get_file_content(file_id))  # caches the listing without the library
    server.library_visible = True
    assert run(fresh.get_file_content(file_id)).content == b"document 0"


def test_deletion_check_never_uses_the_cached_scope(connector):
    adapter, server = connector
    file_id = _first_file_id(adapter)
    before = server.lists_calls()
    assert run(adapter.is_definitively_missing(file_id)) is False
    assert server.lists_calls() == before + 1


def test_one_ntlm_session_serves_sequential_calls_and_a_failed_one_is_discarded(connector):
    adapter, server = connector
    file_id = _first_file_id(adapter)
    run(adapter.get_file_content(file_id))
    run(adapter.get_file_content(file_id))
    assert len(server.sessions) == 1
    server.status["GetFileByServerRelativeUrl('" + NESTED + "/doc-0.txt')/$value"] = "timeout"
    with pytest.raises(TimeoutError):
        run(adapter.get_file_content(file_id))
    server.status.clear()
    run(adapter.get_file_content(file_id))
    assert len(server.sessions) == 2


def test_session_pool_lends_distinct_sessions_caps_idle_and_expires(connector, monkeypatch):
    adapter, server = connector
    clock = _Clock(monkeypatch)
    adapter._settings()
    with ExitStack() as stack:
        borrowed = [
            stack.enter_context(adapter._borrow_session())
            for _ in range(sharepoint_onprem._MAX_IDLE_SESSIONS + 2)
        ]
        assert len({id(session) for session in borrowed}) == len(borrowed)
    assert len(adapter._idle_sessions) == sharepoint_onprem._MAX_IDLE_SESSIONS
    with adapter._borrow_session() as reused:
        assert any(reused is session for session in borrowed)
    clock.now += sharepoint_onprem._SESSION_IDLE_SECONDS + 1
    with adapter._borrow_session() as replacement:
        assert all(replacement is not session for session in borrowed)
    assert len(adapter._idle_sessions) == 1


def test_successful_authentication_is_cached_but_a_failure_is_not(connector, monkeypatch):
    adapter, server = connector
    clock = _Clock(monkeypatch)
    assert run(adapter.authenticate()) is True
    probed = len(server.calls)
    assert run(adapter.authenticate()) is True
    assert len(server.calls) == probed  # status checks no longer fan out to the farm
    clock.now += sharepoint_onprem._AUTH_CACHE_SECONDS + 1
    assert run(adapter.authenticate()) is True
    assert len(server.calls) > probed

    failing = SharePointOnPremConnector(adapter.config)
    server.blocked_site = "/sites/beta"
    assert run(failing.authenticate()) is False
    server.blocked_site = None
    attempts = len(server.calls)
    assert run(failing.authenticate()) is True
    assert len(server.calls) > attempts


# Review pullrequestreview-5834310406-3: identical paths on two approved servers
# must never share an ID, or one server's 404 could delete the other's chunks.

FOREIGN_ORIGIN = "https://other.example.test"
SECOND_ORIGIN = "https://second.example.test"


def _with_origin(identifier, origin):
    decoded = sharepoint_onprem._untoken(identifier)
    decoded[1] = origin
    return sharepoint_onprem._token(decoded)


def test_ids_are_bound_to_the_approved_origin(connector):
    adapter, server = connector
    library, nested = navigate(adapter)
    file_id = run(adapter.list_children(nested["id"], None, 1))["nodes"][0]["id"]
    for identifier in (library["id"], nested["id"], file_id):
        assert sharepoint_onprem._untoken(identifier)[1] == ORIGIN
    before = len(server.calls)
    foreign_file = _with_origin(file_id, FOREIGN_ORIGIN)
    with pytest.raises(ValueError, match="configured SharePoint server"):
        run(adapter.get_file_content(foreign_file))
    assert run(adapter.is_definitively_missing(foreign_file)) is False
    with pytest.raises(ValueError, match="configured SharePoint server"):
        run(adapter.list_children(_with_origin(nested["id"], FOREIGN_ORIGIN)))
    # Layouts minted before the origin was added: rejected, never a deletion.
    legacy_file = sharepoint_onprem._token(["f", SITE, LIBRARY, NESTED + "/doc-0.txt"])
    with pytest.raises(ValueError, match="configured SharePoint server"):
        run(adapter.get_file_content(legacy_file))
    assert run(adapter.is_definitively_missing(legacy_file)) is False
    with pytest.raises(ValueError, match="Invalid SharePoint identifier"):
        run(adapter.list_children(sharepoint_onprem._token(["s", SITE])))
    assert len(server.calls) == before  # rejected before any request


def test_root_url_switch_cannot_reuse_another_servers_ids(connector, monkeypatch):
    adapter, server = connector
    file_id = _first_file_id(adapter)
    monkeypatch.setenv("OPENRAG_SHAREPOINT_ALLOWED_ORIGINS", f"{ORIGIN},{SECOND_ORIGIN}")
    switched = SharePointOnPremConnector({**adapter.config, "root_url": SECOND_ORIGIN})
    before = len(server.calls)
    # The fake server asserts ORIGIN on every request, so a leak fails loudly.
    with pytest.raises(ValueError, match="configured SharePoint server"):
        run(switched.get_file_content(file_id))
    assert run(switched.is_definitively_missing(file_id)) is False
    assert len(server.calls) == before
    first_sites = run(adapter.list_children())["nodes"]
    second_sites = run(switched.list_children())["nodes"]
    for first, second in zip(first_sites, second_sites, strict=True):
        assert first["name"] == second["name"]
        assert first["id"] != second["id"]
        assert switched.filename_for_index(first["id"], "doc.txt") != switched.filename_for_index(
            second["id"], "doc.txt"
        )
