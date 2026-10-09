"""Public-interface tests against a stateful SharePoint REST transport."""

import asyncio
import base64
import io
import json
from urllib.parse import parse_qs, unquote, urlencode, urlsplit

import pytest
import requests
from requests_ntlm import HttpNtlmAuth
from sharepoint_onprem import SharePointOnPremConnector

ORIGIN = "https://sharepoint.example.test"
SITE = "/sites/alpha"
LIBRARY = SITE + "/Docs"
NESTED = LIBRARY + "/team/nested"


def run(awaitable):
    return asyncio.run(awaitable)


def altered_file_id(file_id, *, library, path):
    decoded = json.loads(base64.urlsafe_b64decode(file_id + "=" * (-len(file_id) % 4)))
    decoded[2:] = [library, path]
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

    def get(self, session, url, *, params, **options):
        assert isinstance(session.auth, HttpNtlmAuth)
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
            return self.response(200, {"d": {"Id": "site"}})
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
                items = [{"Name": "team", "ServerRelativeUrl": LIBRARY + "/team"}]
                if self.duplicate_folder:
                    items.append({"Name": "other", "ServerRelativeUrl": LIBRARY + "/other"})
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


def test_missing_library_inventory_cannot_signal_file_deletion(connector):
    adapter, server = connector
    _, nested = navigate(adapter)
    file_id = run(adapter.list_children(nested["id"], None, 1))["nodes"][0]["id"]
    server.status["lists"] = 404
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
