"""Unit tests for the Code Wiki Langflow components.

Covers the logic these components add on top of Langflow: pointer-file and repo URL parsing, safe
archive unpacking, symbol extraction and import resolution, wiki page / chunk construction, and the
OpenSearch query tools. `test_custom_components.py` already runs the generic structural checks
(valid Python, ruff-clean, unique input names, outputs point at real methods) on every file in
`custom_components/openrag/`.

`lfx` is not installed in the backend venv, so it is stubbed (same approach as
`test_openrag_split_text_component.py`). Nothing here touches the network, git, Docling or
OpenSearch: those are replaced with fakes.
"""

import importlib.util
import io
import json
import socket
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType, SimpleNamespace

import httpx
import pytest

COMPONENT_DIR = Path(__file__).resolve().parents[2] / "custom_components" / "openrag"

PY_SOURCE = (
    "class Foo:\n    def bar(self, x):\n        if x:\n            return 1\n        return 2\n"
)

JAVA_SOURCE = """package org.x;

import org.y.Util;

public class Hello {
    public String hi() {
        return "hi";
    }
    abstract void nope();
    private static final class Inner {
        int f() { return 1; }
    }
}
interface Shape {
    double area();
}
enum Color { RED, GREEN }
record Pt(int x, int y) {}
"""

JS_SOURCE = (
    "import a from './a';\nimport {b} from '../b.js';\n"
    "export function f() {\n  return 1;\n}\nclass K {\n  m() {\n    return 2;\n  }\n}\n"
)


# --------------------------------------------------------------------------------------
# lfx stubs and module loading
# --------------------------------------------------------------------------------------
class _Input:
    """Stands in for every lfx input type; keeps the keyword arguments as attributes."""

    def __init__(self, *_args, **kwargs):
        self.__dict__.update(kwargs)


class _Component:
    def log(self, *_args, **_kwargs):
        pass


class _Data:
    def __init__(self, data=None, **_kwargs):
        self.data = data if data is not None else {}


def _load(monkeypatch: pytest.MonkeyPatch, filename: str) -> ModuleType:
    stubs = {
        name: ModuleType(name)
        for name in (
            "lfx",
            "lfx.custom",
            "lfx.custom.custom_component",
            "lfx.custom.custom_component.component",
            "lfx.io",
            "lfx.schema",
            "lfx.schema.data",
        )
    }
    stubs["lfx.custom.custom_component.component"].Component = _Component
    for input_name in (
        "BoolInput",
        "DropdownInput",
        "HandleInput",
        "IntInput",
        "MessageTextInput",
        "Output",
        "SecretStrInput",
        "StrInput",
    ):
        setattr(stubs["lfx.io"], input_name, _Input)
    stubs["lfx.schema.data"].Data = _Data
    for name, module in stubs.items():
        monkeypatch.setitem(sys.modules, name, module)

    path = COMPONENT_DIR / filename
    spec = importlib.util.spec_from_file_location(f"_codewiki_under_test_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make(cls, **attrs):
    """Instantiate a component with its declared input defaults, then apply overrides."""
    inst = cls()
    for inp in cls.inputs:
        if hasattr(inp, "name"):
            setattr(inst, inp.name, getattr(inp, "value", None))
    for key, value in attrs.items():
        setattr(inst, key, value)
    return inst


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    for name in (
        "REPO_URL",
        "CODEWIKI_REPO_URL",
        "CODEWIKI_LOCAL_PATH",
        "CODEWIKI_TOKEN_HOSTS",
        "CODEWIKI_ALLOW_PRIVATE_HOSTS",
        "DOCLING_SERVE_URL",
        "GITHUB_TOKEN",
        "GH_TOKEN",
        "GITLAB_TOKEN",
        "OPENSEARCH_URL",
        "OPENSEARCH_USERNAME",
        "OPENSEARCH_PASSWORD",
        "OPENSEARCH_JWT_TOKEN",
        "OPENSEARCH_INDEX_NAME",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def rl(monkeypatch):
    return _load(monkeypatch, "code_wiki_repo_loader.py")


@pytest.fixture
def builder(monkeypatch):
    return _load(monkeypatch, "code_wiki_builder.py")


@pytest.fixture
def search(monkeypatch):
    return _load(monkeypatch, "code_wiki_search.py")


@pytest.fixture
def reader(monkeypatch):
    return _load(monkeypatch, "code_wiki_reader.py")


@pytest.fixture
def deps(monkeypatch):
    return _load(monkeypatch, "code_wiki_deps.py")


# --------------------------------------------------------------------------------------
# Defaults that must stay safe
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("fixture", "cls"),
    [
        ("search", "CodeWikiSearch"),
        ("reader", "CodeWikiReader"),
        ("deps", "CodeWikiDeps"),
    ],
)
def test_opensearch_password_and_token_defaults_are_empty(request, fixture, cls):
    """A real password committed as an input default would ship to every install."""
    mod = request.getfixturevalue(fixture)
    inputs = {i.name: i for i in getattr(mod, cls).inputs if hasattr(i, "name")}
    assert inputs["password"].value == ""
    assert inputs["jwt_token"].value == ""


def test_repo_loader_access_token_default_is_empty(rl):
    inputs = {i.name: i for i in rl.RepoLoader.inputs if hasattr(i, "name")}
    assert inputs["access_token"].value == ""


def test_builder_input_defaults(builder):
    inputs = {i.name: i for i in builder.CodeWikiBuilder.inputs if hasattr(i, "name")}
    assert inputs["chunk_size"].value == 3000
    assert inputs["symbol_page_min_lines"].value == 50


# --------------------------------------------------------------------------------------
# RepoLoader: pointer file parsing
# --------------------------------------------------------------------------------------
class TestParsePointer:
    def _parse(self, rl, text):
        return _make(rl.RepoLoader, pointer_data=text)._parse_pointer()

    def test_url_only(self, rl):
        assert self._parse(rl, "https://github.com/owner/repo\n") == (
            "https://github.com/owner/repo",
            "",
            "",
        )

    def test_url_with_subtree_and_ref(self, rl):
        text = "https://github.com/owner/repo\nsubtree: src/pkg\nref: main\n"
        assert self._parse(rl, text) == ("https://github.com/owner/repo", "main", "src/pkg")

    def test_branch_is_an_alias_for_ref(self, rl):
        assert self._parse(rl, "https://github.com/o/r\nbranch: dev")[1] == "dev"

    @pytest.mark.parametrize("key", ["repo", "url"])
    def test_explicit_keys(self, rl, key):
        text = f"some notes\n{key}: https://github.com/owner/repo\n"
        assert self._parse(rl, text)[0] == "https://github.com/owner/repo"

    def test_docling_merges_lines_into_one_paragraph(self, rl):
        merged = "https://github.com/owner/repo subtree: src/pkg ref: main"
        assert self._parse(rl, merged) == ("https://github.com/owner/repo", "main", "src/pkg")

    def test_nothing_found_returns_empties(self, rl):
        assert self._parse(rl, "") == ("", "", "")
        assert self._parse(rl, "no url in here") == ("", "", "")

    def test_ssh_url_is_found(self, rl):
        assert (
            self._parse(rl, "git@github.com:owner/repo.git")[0] == "git@github.com:owner/repo.git"
        )


class _FakeDoclingResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _patch_docling(monkeypatch, payload):
    class Client:
        def __init__(self, *_a, **_k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def get(self, _url):
            return _FakeDoclingResponse(payload)

    monkeypatch.setattr(httpx, "Client", Client)


def _docling_loader(rl, **attrs):
    return _make(
        rl.RepoLoader, docling_task_id="task-1", docling_url="http://docling:5001", **attrs
    )


class TestDoclingPointerText:
    def test_json_content_texts_used_when_md_content_is_null(self, rl, monkeypatch):
        """The OpenRAG backend asks Docling for JSON only, so md_content is null."""
        payload = {
            "status": "success",
            "errors": [],
            "document": {
                "filename": "pointer.txt",
                "md_content": None,
                "json_content": {
                    "texts": [
                        {"text": "https://github.com/owner/repo"},
                        {"text": "subtree: src/pkg ref: main"},
                    ]
                },
            },
        }
        _patch_docling(monkeypatch, payload)
        assert _docling_loader(rl)._parse_pointer() == (
            "https://github.com/owner/repo",
            "main",
            "src/pkg",
        )

    def test_markdown_link_is_reduced_to_the_url(self, rl, monkeypatch):
        payload = {
            "status": "success",
            "document": {
                "md_content": "[https://github.com/owner/repo](https://github.com/owner/repo)",
                "json_content": None,
            },
        }
        _patch_docling(monkeypatch, payload)
        assert _docling_loader(rl)._parse_pointer()[0] == "https://github.com/owner/repo"

    def test_skipped_file_gives_a_clear_error_instead_of_no_repo_source(self, rl, monkeypatch):
        """Docling reports the task as successful but refuses archives and source files."""
        payload = {
            "status": "skipped",
            "document": {"filename": "repo_renamed.txt", "md_content": None, "json_content": None},
            "errors": [{"error_message": "File format not allowed: repo_renamed.txt"}],
        }
        _patch_docling(monkeypatch, payload)
        loader = _docling_loader(rl)
        assert loader._parse_pointer() == ("", "", "")
        with pytest.raises(ValueError, match="Docling did not convert repo_renamed.txt") as exc:
            loader._obtain_repo()
        message = str(exc.value)
        assert "File format not allowed" in message
        assert "pointer .txt" in message

    def test_no_task_id_means_no_docling_call(self, rl, monkeypatch):
        def boom(*_a, **_k):
            raise AssertionError("Docling must not be called without a task id")

        monkeypatch.setattr(httpx, "Client", boom)
        assert _make(rl.RepoLoader)._parse_pointer() == ("", "", "")


class TestGlobalValue:
    @pytest.mark.parametrize("raw", ["", None, "None", "none", "DOCLING_TASK_ID", "REPO_URL"])
    def test_unresolved_or_empty_becomes_empty(self, rl, raw):
        assert rl.RepoLoader._global_value(raw) == ""

    def test_real_value_is_kept(self, rl):
        assert rl.RepoLoader._global_value("abc-123") == "abc-123"

    def test_secret_str_is_unwrapped(self, rl):
        secret = SimpleNamespace(get_secret_value=lambda: "tok-1")
        assert rl.RepoLoader._global_value(secret) == "tok-1"


def test_no_repo_source_error_lists_what_was_tried(rl):
    with pytest.raises(ValueError, match="No repo source") as exc:
        _make(rl.RepoLoader)._obtain_repo()
    message = str(exc.value)
    for tried in ("pointer_data", "repo_url", "local_path"):
        assert tried in message


# --------------------------------------------------------------------------------------
# RepoLoader: repo URL forms and token host policy
# --------------------------------------------------------------------------------------
class TestParseRepoUrl:
    def test_plain_https(self, rl):
        info = rl.parse_repo_url("https://github.com/owner/repo")
        assert (info["kind"], info["owner"], info["repo"], info["ref"], info["subdir"]) == (
            "git",
            "owner",
            "repo",
            "",
            "",
        )

    def test_dot_git_suffix(self, rl):
        info = rl.parse_repo_url("https://github.com/owner/repo.git")
        assert info["repo"] == "repo"
        assert info["url"] == "https://github.com/owner/repo"

    def test_tree_url_gives_ref_and_subdir(self, rl):
        info = rl.parse_repo_url("https://github.com/owner/repo/tree/main/src/pkg")
        assert (info["ref"], info["subdir"], info["url"]) == (
            "main",
            "src/pkg",
            "https://github.com/owner/repo",
        )

    def test_tree_url_with_ref_only(self, rl):
        info = rl.parse_repo_url("https://github.com/owner/repo/tree/v1.2")
        assert (info["ref"], info["subdir"]) == ("v1.2", "")

    def test_scp_style_ssh(self, rl):
        info = rl.parse_repo_url("git@github.com:owner/repo.git")
        assert (info["scheme"], info["host"], info["owner"], info["repo"]) == (
            "ssh",
            "github.com",
            "owner",
            "repo",
        )

    def test_github_enterprise_host(self, rl):
        info = rl.parse_repo_url("https://github.example.com/team/proj")
        assert rl.host_kind(info["host"]) == "github"
        assert info["owner"] == "team"

    def test_gitlab_nested_group_with_tree(self, rl):
        info = rl.parse_repo_url("https://gitlab.com/group/sub/proj/-/tree/dev/lib")
        assert (info["owner"], info["repo"], info["ref"], info["subdir"]) == (
            "group/sub",
            "proj",
            "dev",
            "lib",
        )

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/a/repo.zip",
            "https://example.com/a/repo.tar.gz",
            "https://example.com/a/repo.tgz?sig=abc",
        ],
    )
    def test_direct_archive_urls(self, rl, url):
        info = rl.parse_repo_url(url)
        assert info["kind"] == "archive"
        assert info["fetch_url"].startswith("https://example.com/a/repo.")

    def test_archive_query_string_is_kept_for_fetch_but_not_in_the_canonical_url(self, rl):
        info = rl.parse_repo_url("https://example.com/a/repo.tgz?sig=abc")
        assert "sig=abc" in info["fetch_url"]
        assert "sig" not in info["url"]

    def test_credentials_are_not_kept(self, rl):
        assert "secret" not in rl.parse_repo_url("https://user:secret@github.com/o/r")["url"]

    def test_unparseable_input_is_returned_unchanged(self, rl):
        assert rl.parse_repo_url("not a url")["url"] == "not a url"

    def test_file_scheme_is_not_treated_as_http(self, rl):
        assert rl.parse_repo_url("file:///etc/passwd")["scheme"] == ""


class TestTokenHosts:
    def test_known_hosts_get_a_token(self, rl):
        assert rl.token_allowed("github.com")
        assert rl.token_allowed("gitlab.com")

    def test_other_hosts_do_not(self, rl):
        assert not rl.token_allowed("evil.example.com")

    def test_hosts_can_be_added_by_env(self, rl, monkeypatch):
        monkeypatch.setenv("CODEWIKI_TOKEN_HOSTS", "github.example.com, other.example.com")
        assert rl.token_allowed("github.example.com")
        assert rl.token_allowed("other.example.com")

    def test_resolve_token_prefers_the_input_over_env(self, rl, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "from-env")
        secret = SimpleNamespace(get_secret_value=lambda: "from-input")
        assert (
            _make(rl.RepoLoader, access_token=secret)._resolve_token("github.com") == "from-input"
        )
        assert _make(rl.RepoLoader)._resolve_token("github.com") == "from-env"

    def test_resolve_token_uses_the_gitlab_variable_for_gitlab(self, rl, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "gh")
        monkeypatch.setenv("GITLAB_TOKEN", "gl")
        assert _make(rl.RepoLoader)._resolve_token("gitlab.com") == "gl"

    def test_untrusted_host_never_gets_a_token(self, rl, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "gh")
        assert _make(rl.RepoLoader)._resolve_token("evil.example.com") == ""


# --------------------------------------------------------------------------------------
# RepoLoader: archive unpacking
# --------------------------------------------------------------------------------------
def _make_zip(path, entries, symlinks=()):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
        for name, target in symlinks:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, target)
    return path


def _make_tar(path, entries, extra=None):
    with tarfile.open(path, "w:gz") as tf:
        for name, data in entries.items():
            raw = data.encode()
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            tf.addfile(info, io.BytesIO(raw))
        for info in extra or []:
            tf.addfile(info)
    return path


def _repo_paths(rl, root):
    return sorted(f["repo_path"] for f in rl.walk_files(root))


class TestUnpackArchive:
    def test_zip_keeps_exact_source_text(self, rl, tmp_path):
        """Indentation and line numbers survive, unlike a Docling conversion."""
        z = _make_zip(
            tmp_path / "ok.zip",
            {
                "src/pkg/foo.py": PY_SOURCE,
                "src/Hello.java": "package org.x;\npublic class Hello {}\n",
                "README.md": "# Demo\n",
            },
        )
        root = rl.unpack_archive(str(z), str(tmp_path / "out"))
        files = {f["repo_path"]: f for f in rl.walk_files(root)}
        assert set(files) == {"src/pkg/foo.py", "src/Hello.java", "README.md"}
        assert files["src/pkg/foo.py"]["text"] == PY_SOURCE
        symbols = rl.extract_symbols(files["src/pkg/foo.py"]["text"], "python")
        assert {"symbol": "Foo", "kind": "class", "line_start": 1, "line_end": 5} in symbols

    def test_archive_is_detected_by_content_not_by_name(self, rl, tmp_path):
        z = _make_zip(tmp_path / "ok.zip", {"a.py": "x = 1\n"})
        renamed = tmp_path / "repo.txt"
        renamed.write_bytes(z.read_bytes())
        root = rl.unpack_archive(str(renamed), str(tmp_path / "out"))
        assert _repo_paths(rl, root) == ["a.py"]

    def test_single_wrapping_directory_is_stripped(self, rl, tmp_path):
        z = _make_zip(
            tmp_path / "wrap.zip",
            {"owner-repo-abc123/a.py": "x = 1\n", "owner-repo-abc123/b/c.py": "y = 2\n"},
        )
        root = rl.unpack_archive(str(z), str(tmp_path / "out"))
        assert _repo_paths(rl, root) == ["a.py", "b/c.py"]

    def test_tar_gz(self, rl, tmp_path):
        t = _make_tar(tmp_path / "r.tar.gz", {"r/m.py": PY_SOURCE, "r/n.js": "let a = 1;\n"})
        root = rl.unpack_archive(str(t), str(tmp_path / "out"))
        assert _repo_paths(rl, root) == ["m.py", "n.js"]

    @pytest.mark.parametrize(
        "name",
        ["../evil.py", "a/../../evil.py", "/etc/evil.py", "C:/evil.py", "..\\evil.py"],
    )
    def test_zip_slip_and_absolute_paths_are_rejected(self, rl, tmp_path, name):
        z = _make_zip(tmp_path / "bad.zip", {name: "x"})
        with pytest.raises(rl.ArchiveError, match="unsafe path"):
            rl.unpack_archive(str(z), str(tmp_path / "out"))
        assert not (tmp_path / "evil.py").exists()
        assert not Path("/etc/evil.py").exists()

    def test_tar_path_traversal_is_rejected(self, rl, tmp_path):
        t = _make_tar(tmp_path / "bad.tar.gz", {"../evil.py": "x"})
        with pytest.raises(rl.ArchiveError, match="unsafe path"):
            rl.unpack_archive(str(t), str(tmp_path / "out"))
        assert not (tmp_path / "evil.py").exists()

    def test_zip_symlinks_are_skipped(self, rl, tmp_path):
        z = _make_zip(
            tmp_path / "s.zip", {"ok.py": "a = 1\n"}, symlinks=[("link.py", "/etc/passwd")]
        )
        root = rl.unpack_archive(str(z), str(tmp_path / "out"))
        assert _repo_paths(rl, root) == ["ok.py"]

    def test_tar_symlinks_and_hard_links_are_skipped(self, rl, tmp_path):
        sym = tarfile.TarInfo("link.py")
        sym.type = tarfile.SYMTYPE
        sym.linkname = "/etc/passwd"
        hard = tarfile.TarInfo("hard.py")
        hard.type = tarfile.LNKTYPE
        hard.linkname = "ok.py"
        t = _make_tar(tmp_path / "s.tar.gz", {"ok.py": "a = 1\n"}, extra=[sym, hard])
        root = rl.unpack_archive(str(t), str(tmp_path / "out"))
        assert _repo_paths(rl, root) == ["ok.py"]

    def test_file_count_cap(self, rl, tmp_path):
        z = _make_zip(tmp_path / "many.zip", {f"d/f{i}.py": "x = 1\n" for i in range(12)})
        with pytest.raises(rl.ArchiveError, match="more than 10 source files"):
            rl.unpack_archive(str(z), str(tmp_path / "out"), max_files=10)

    def test_size_cap_counts_bytes_actually_written(self, rl, tmp_path):
        z = _make_zip(tmp_path / "big.zip", {"a.py": "x" * 3000, "b.py": "y" * 3000})
        with pytest.raises(rl.ArchiveError, match="expands beyond"):
            rl.unpack_archive(str(z), str(tmp_path / "out"), max_bytes=4000)

    def test_ignored_trees_do_not_count_toward_the_caps(self, rl, tmp_path):
        entries = {f"node_modules/m{i}.js": "x = 1\n" for i in range(50)}
        entries["a.py"] = "x = 1\n"
        z = _make_zip(tmp_path / "ign.zip", entries)
        root = rl.unpack_archive(str(z), str(tmp_path / "out"), max_files=5)
        assert _repo_paths(rl, root) == ["a.py"]

    def test_not_an_archive(self, rl, tmp_path):
        plain = tmp_path / "plain.txt"
        plain.write_text("hello")
        with pytest.raises(rl.ArchiveError, match="not a zip or tar"):
            rl.unpack_archive(str(plain), str(tmp_path / "out"))


class TestWalkFilesSymlinks:
    """A cloned repo or local_path directory can contain real symlinks (unlike archives, whose
    link entries are skipped at unpack time). walk_files must never read through them."""

    def _repo_with_secret(self, tmp_path):
        secret = tmp_path / "server_secret.env"
        secret.write_text("OPENSEARCH_PASSWORD=hunter2\n")
        repo = tmp_path / "repo"
        (repo / "pkg").mkdir(parents=True)
        (repo / "pkg/ok.py").write_text("x = 1\n")
        return repo, secret

    def test_symlinked_file_is_skipped(self, rl, tmp_path):
        repo, secret = self._repo_with_secret(tmp_path)
        (repo / "settings.py").symlink_to(secret)
        files = rl.walk_files(repo)
        assert [f["repo_path"] for f in files] == ["pkg/ok.py"]
        assert not any("hunter2" in f["text"] for f in files)

    def test_symlinked_directory_is_skipped(self, rl, tmp_path):
        repo, secret = self._repo_with_secret(tmp_path)
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "leak.py").write_text(secret.read_text())
        (repo / "linked").symlink_to(outside, target_is_directory=True)
        assert _repo_paths(rl, repo) == ["pkg/ok.py"]

    def test_link_to_a_file_inside_the_repo_is_skipped_too(self, rl, tmp_path):
        repo, _secret = self._repo_with_secret(tmp_path)
        (repo / "alias.py").symlink_to(repo / "pkg/ok.py")
        assert _repo_paths(rl, repo) == ["pkg/ok.py"]

    def test_non_regular_files_are_not_read(self, rl, tmp_path):
        repo, _secret = self._repo_with_secret(tmp_path)
        assert rl._read_text(tmp_path) is None  # a directory
        assert rl._read_text(repo / "pkg/ok.py") == "x = 1\n"

    def test_local_path_directory_with_a_symlink(self, rl, tmp_path):
        repo, secret = self._repo_with_secret(tmp_path)
        (repo / "config.py").symlink_to(secret)
        data = _make(rl.RepoLoader, local_path=str(repo)).load_repo().data["repo"]
        assert [f["repo_path"] for f in data["files"]] == ["pkg/ok.py"]
        assert repo.exists(), "a user-supplied local_path is never deleted"


# --------------------------------------------------------------------------------------
# RepoLoader: where the repo comes from
# --------------------------------------------------------------------------------------
class TestLocalPath:
    def test_directory(self, rl, tmp_path):
        (tmp_path / "a.py").write_text("x = 1\n")
        root, url, ref, subdir = _make(rl.RepoLoader, local_path=str(tmp_path))._obtain_repo()
        assert (root, url, ref, subdir) == (str(tmp_path), "", "", "")

    def test_zip_file(self, rl, tmp_path):
        z = _make_zip(tmp_path / "repo.zip", {"src/pkg/foo.py": PY_SOURCE, "README.md": "# Demo\n"})
        data = _make(rl.RepoLoader, local_path=str(z)).load_repo().data["repo"]
        assert sorted(f["repo_path"] for f in data["files"]) == ["README.md", "src/pkg/foo.py"]

    def test_zip_named_txt(self, rl, tmp_path):
        z = _make_zip(tmp_path / "repo.zip", {"a.py": "x = 1\n"})
        renamed = tmp_path / "repo_renamed.txt"
        renamed.write_bytes(z.read_bytes())
        data = _make(rl.RepoLoader, local_path=str(renamed)).load_repo().data["repo"]
        assert [f["repo_path"] for f in data["files"]] == ["a.py"]

    def test_unusable_file_names_the_file(self, rl, tmp_path):
        plain = tmp_path / "plain.txt"
        plain.write_text("hello")
        with pytest.raises(rl.ArchiveError, match="plain.txt"):
            _make(rl.RepoLoader, local_path=str(plain))._obtain_repo()

    def test_env_fallback(self, rl, tmp_path, monkeypatch):
        (tmp_path / "a.py").write_text("x = 1\n")
        monkeypatch.setenv("CODEWIKI_LOCAL_PATH", str(tmp_path))
        assert _make(rl.RepoLoader)._obtain_repo()[0] == str(tmp_path)


class _GitStub:
    """Replaces subprocess.run for `git clone`: records the call and writes a small repo."""

    def __init__(self):
        self.cmd = []
        self.env = {}

    def __call__(self, cmd, **kwargs):
        self.cmd = cmd
        self.env = kwargs.get("env", {})
        dest = Path(cmd[-1])
        (dest / "src" / "pkg").mkdir(parents=True)
        (dest / "other").mkdir()
        (dest / "src/pkg/a.py").write_text("x = 1\n")
        (dest / "other/b.py").write_text("y = 1\n")
        return SimpleNamespace(returncode=0)


@pytest.fixture
def public_dns(monkeypatch, rl):
    """Every repo host resolves to a public address; no real DNS lookups."""
    monkeypatch.setattr(
        rl.socket,
        "getaddrinfo",
        lambda host, port, *_a, **_k: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 443))
        ],
    )


@pytest.fixture
def git(monkeypatch, rl, public_dns):
    stub = _GitStub()
    monkeypatch.setattr(subprocess, "run", stub)
    monkeypatch.setattr(rl.shutil, "which", lambda _name: "/usr/bin/git")
    return stub


def _git_config(env):
    """GIT_CONFIG_KEY_n / GIT_CONFIG_VALUE_n pairs as a dict."""
    n = int(env.get("GIT_CONFIG_COUNT", "0"))
    return {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"] for i in range(n)}


class TestGitClone:
    def test_tree_url_sets_branch_and_subtree(self, rl, git):
        loader = _make(rl.RepoLoader, repo_url="https://github.com/owner/repo/tree/dev/src/pkg")
        data = loader.load_repo().data["repo"]
        assert git.cmd[git.cmd.index("--branch") + 1] == "dev"
        assert git.cmd[-2] == "https://github.com/owner/repo"
        assert [f["repo_path"] for f in data["files"]] == ["src/pkg/a.py"]
        assert (data["repo_url"], data["repo_ref"]) == ("https://github.com/owner/repo", "dev")

    def test_explicit_ref_and_subtree_win_over_the_url(self, rl, git):
        loader = _make(
            rl.RepoLoader,
            repo_url="https://github.com/owner/repo/tree/dev/src/pkg",
            repo_ref="v9",
            subtree="other",
        )
        data = loader.load_repo().data["repo"]
        assert git.cmd[git.cmd.index("--branch") + 1] == "v9"
        assert [f["repo_path"] for f in data["files"]] == ["other/b.py"]

    def test_pointer_url_wins_over_the_repo_url_field(self, rl, git):
        loader = _make(
            rl.RepoLoader,
            pointer_data="https://github.com/from/pointer",
            repo_url="https://github.com/from/field",
        )
        loader.load_repo()
        assert git.cmd[-2] == "https://github.com/from/pointer"

    def test_url_cannot_be_read_as_a_git_option(self, rl, git):
        _make(rl.RepoLoader, repo_url="https://github.com/o/r")._obtain_repo()
        assert git.cmd[-3] == "--"

    def test_git_transports_are_restricted_and_prompts_disabled(self, rl, git):
        _make(rl.RepoLoader, repo_url="https://github.com/o/r")._obtain_repo()
        assert git.env["GIT_ALLOW_PROTOCOL"] == "https:ssh"
        assert git.env["GIT_TERMINAL_PROMPT"] == "0"

    def test_symlinks_are_checked_out_as_plain_files(self, rl, git):
        _make(rl.RepoLoader, repo_url="https://github.com/o/r")._obtain_repo()
        assert _git_config(git.env)["core.symlinks"] == "false"

    def test_token_travels_in_the_environment_only(self, rl, git, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_SECRET123")
        loader = _make(rl.RepoLoader, repo_url="https://github.com/o/r")
        root, url, _ref, _subdir = loader._obtain_repo()
        assert not any("SECRET123" in part for part in git.cmd)
        assert "SECRET123" not in url
        assert "SECRET123" not in str(getattr(loader, "status", ""))
        header = _git_config(git.env)["http.extraHeader"].split("Basic ")[1]
        import base64

        assert base64.b64decode(header).decode() == "x-access-token:ghp_SECRET123"
        assert not (Path(root) / ".git" / "config").exists()

    def test_access_token_input_beats_env(self, rl, git, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "from-env")
        secret = SimpleNamespace(get_secret_value=lambda: "from-input")
        _make(rl.RepoLoader, repo_url="https://github.com/o/r", access_token=secret)._obtain_repo()
        import base64

        header = _git_config(git.env)["http.extraHeader"].split("Basic ")[1]
        assert base64.b64decode(header).decode() == "x-access-token:from-input"

    def test_no_token_is_sent_to_an_untrusted_host(self, rl, git, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_SECRET123")
        _make(rl.RepoLoader, repo_url="https://evil.example.com/o/r")._obtain_repo()
        assert "http.extraHeader" not in _git_config(git.env)

    def test_ssh_urls_are_cloned_without_an_http_header(self, rl, git, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_SECRET123")
        _make(rl.RepoLoader, repo_url="git@github.com:owner/repo.git")._obtain_repo()
        assert git.cmd[-2] == "git@github.com:owner/repo.git"
        assert "http.extraHeader" not in _git_config(git.env)

    def test_plain_http_url_is_refused(self, rl, git, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_SECRET123")
        with pytest.raises(ValueError, match="Plain http"):
            _make(rl.RepoLoader, repo_url="http://github.com/o/r")._obtain_repo()
        assert git.cmd == []

    def test_http_is_allowed_with_the_opt_in_but_never_carries_the_token(
        self, rl, git, monkeypatch
    ):
        monkeypatch.setenv("CODEWIKI_ALLOW_PRIVATE_HOSTS", "1")
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_SECRET123")
        _make(rl.RepoLoader, repo_url="http://github.com/o/r")._obtain_repo()
        assert git.cmd[-2] == "http://github.com/o/r"
        assert "http.extraHeader" not in _git_config(git.env)
        assert git.env["GIT_ALLOW_PROTOCOL"] == "https:http:ssh"
        assert not any("Authorization" in v for v in _git_config(git.env).values())

    @pytest.mark.parametrize("ip", ["10.0.0.5", "127.0.0.1", "169.254.169.254", "192.168.1.9"])
    def test_clone_from_an_internal_host_is_refused(self, rl, git, monkeypatch, ip):
        monkeypatch.setattr(
            rl.socket,
            "getaddrinfo",
            lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))],
        )
        with pytest.raises(RuntimeError, match="not a public address"):
            _make(rl.RepoLoader, repo_url="https://git.internal.example/o/r")._obtain_repo()
        assert git.cmd == []

    def test_ssh_to_an_internal_host_is_refused(self, rl, git, monkeypatch):
        monkeypatch.setattr(
            rl.socket,
            "getaddrinfo",
            lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 22))],
        )
        with pytest.raises(RuntimeError, match="not a public address"):
            _make(rl.RepoLoader, repo_url="git@gitserver.corp:team/repo.git")._obtain_repo()
        assert git.cmd == []

    def test_internal_git_hosts_can_be_allowed_explicitly(self, rl, git, monkeypatch):
        monkeypatch.setenv("CODEWIKI_ALLOW_PRIVATE_HOSTS", "1")
        monkeypatch.setattr(
            rl.socket,
            "getaddrinfo",
            lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))],
        )
        _make(rl.RepoLoader, repo_url="https://git.internal.example/o/r")._obtain_repo()
        assert git.cmd[-2] == "https://git.internal.example/o/r"

    def test_git_does_not_follow_http_redirects(self, rl, git):
        _make(rl.RepoLoader, repo_url="https://github.com/o/r")._obtain_repo()
        assert _git_config(git.env)["http.followRedirects"] == "false"

    def test_failure_message_does_not_leak_the_token(self, rl, public_dns, monkeypatch):
        def failing(cmd, **_kwargs):
            raise subprocess.CalledProcessError(
                128,
                cmd,
                stderr="fatal: unable to access https://x-access-token:ghp_LEAK@github.com/o/r",
            )

        monkeypatch.setattr(subprocess, "run", failing)
        monkeypatch.setattr(rl.shutil, "which", lambda _name: "/usr/bin/git")
        secret = SimpleNamespace(get_secret_value=lambda: "ghp_LEAK")
        loader = _make(rl.RepoLoader, repo_url="https://github.com/o/r", access_token=secret)
        with pytest.raises(RuntimeError, match="git clone failed") as exc:
            loader._obtain_repo()
        assert "ghp_LEAK" not in str(exc.value)

    def test_private_repo_hint_when_no_token(self, rl, public_dns, monkeypatch):
        def failing(cmd, **_kwargs):
            raise subprocess.CalledProcessError(128, cmd, stderr="fatal: Authentication failed")

        monkeypatch.setattr(subprocess, "run", failing)
        monkeypatch.setattr(rl.shutil, "which", lambda _name: "/usr/bin/git")
        with pytest.raises(RuntimeError, match="Access token"):
            _make(rl.RepoLoader, repo_url="https://github.com/o/r")._obtain_repo()

    @pytest.mark.parametrize("url", ["file:///etc", "ext::sh -c id", "ftp://example.com/r"])
    def test_other_schemes_are_refused(self, rl, git, url):
        with pytest.raises(ValueError, match="Unsupported repo URL"):
            _make(rl.RepoLoader, repo_url=url)._obtain_repo()
        assert git.cmd == []


class TestTempDirCleanup:
    """Clone / unpack directories are deleted once load_repo has read the files into memory."""

    @pytest.fixture
    def tempdirs(self, rl, monkeypatch, tmp_path):
        made = []
        real = rl.tempfile.mkdtemp

        def tracking(**kw):
            d = real(dir=tmp_path, **kw)
            made.append(Path(d))
            return d

        monkeypatch.setattr(rl.tempfile, "mkdtemp", tracking)
        return made

    def test_clone_directory_is_removed_after_a_successful_load(self, rl, git, tempdirs):
        data = _make(rl.RepoLoader, repo_url="https://github.com/o/r").load_repo().data["repo"]
        assert sorted(f["repo_path"] for f in data["files"]) == ["other/b.py", "src/pkg/a.py"]
        assert len(tempdirs) == 1
        assert not tempdirs[0].exists()

    def test_clone_directory_is_removed_when_git_fails(self, rl, monkeypatch, tempdirs):
        def failing(cmd, **_kwargs):
            raise subprocess.CalledProcessError(128, cmd, stderr="fatal: not found")

        monkeypatch.setattr(subprocess, "run", failing)
        monkeypatch.setattr(rl.shutil, "which", lambda _name: "/usr/bin/git")
        monkeypatch.setattr(
            rl.socket,
            "getaddrinfo",
            lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
        )
        with pytest.raises(RuntimeError, match="git clone failed"):
            _make(rl.RepoLoader, repo_url="https://github.com/o/r").load_repo()
        assert tempdirs and not any(d.exists() for d in tempdirs)

    def test_unpacked_local_archive_is_removed(self, rl, tmp_path, tempdirs):
        z = _make_zip(tmp_path / "repo.zip", {"a.py": "x = 1\n"})
        _make(rl.RepoLoader, local_path=str(z)).load_repo()
        assert len(tempdirs) == 1
        assert not tempdirs[0].exists()
        assert z.exists(), "the user's archive itself is never deleted"

    def test_directory_is_removed_when_walking_fails(self, rl, git, tempdirs, monkeypatch):
        def boom(*_a, **_k):
            raise OSError("disk error")

        monkeypatch.setattr(rl, "walk_files", boom)
        with pytest.raises(OSError, match="disk error"):
            _make(rl.RepoLoader, repo_url="https://github.com/o/r").load_repo()
        assert tempdirs and not any(d.exists() for d in tempdirs)

    def test_local_path_directory_is_kept(self, rl, tmp_path, tempdirs):
        (tmp_path / "a.py").write_text("x = 1\n")
        _make(rl.RepoLoader, local_path=str(tmp_path)).load_repo()
        assert tempdirs == []
        assert (tmp_path / "a.py").exists()


class TestGitlessTarball:
    """No git binary (hosted Langflow image): the repo is fetched as a tarball over HTTPS."""

    @pytest.fixture
    def fetched(self, rl, monkeypatch, tmp_path):
        tarball = _make_tar(tmp_path / "src.tar.gz", {"r/m.py": PY_SOURCE})
        calls = []

        def fake_fetch(_self, url, headers, dest, *, guard):
            calls.append((url, dict(headers), guard))
            Path(dest).write_bytes(tarball.read_bytes())

        monkeypatch.setattr(rl.RepoLoader, "_fetch", fake_fetch)
        monkeypatch.setattr(rl.shutil, "which", lambda _name: None)
        monkeypatch.setattr(
            rl.socket,
            "getaddrinfo",
            lambda host, port, *_a, **_k: [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 443))
            ],
        )
        return calls

    def test_github_com(self, rl, fetched, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_T")
        loader = _make(rl.RepoLoader, repo_url="https://github.com/owner/repo/tree/dev/sub")
        root, *_ = loader._obtain_repo()
        url, headers, guard = fetched[-1]
        assert url == "https://api.github.com/repos/owner/repo/tarball/dev"
        assert headers["Authorization"] == "Bearer ghp_T"
        assert guard is True, "tarball downloads use the public-https guard on every hop"
        assert _repo_paths(rl, root) == ["m.py"]

    def test_internal_host_with_a_github_label_is_refused(self, rl, fetched, monkeypatch):
        monkeypatch.setattr(
            rl.socket,
            "getaddrinfo",
            lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443))],
        )
        with pytest.raises(RuntimeError, match="not a public address"):
            _make(rl.RepoLoader, repo_url="https://github.internal.corp/team/proj")._obtain_repo()
        assert fetched == []

    def test_github_enterprise_uses_api_v3_and_gets_no_token_by_default(
        self, rl, fetched, monkeypatch
    ):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_T")
        _make(rl.RepoLoader, repo_url="https://github.example.com/team/proj")._obtain_repo()
        url, headers, _guard = fetched[-1]
        assert url == "https://github.example.com/api/v3/repos/team/proj/tarball"
        assert "Authorization" not in headers

    def test_github_enterprise_gets_the_token_when_listed(self, rl, fetched, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_T")
        monkeypatch.setenv("CODEWIKI_TOKEN_HOSTS", "github.example.com")
        _make(rl.RepoLoader, repo_url="https://github.example.com/team/proj")._obtain_repo()
        assert fetched[-1][1]["Authorization"] == "Bearer ghp_T"

    def test_gitlab(self, rl, fetched, monkeypatch):
        monkeypatch.setenv("GITLAB_TOKEN", "glpat_T")
        _make(
            rl.RepoLoader, repo_url="https://gitlab.com/group/proj", repo_ref="main"
        )._obtain_repo()
        url, headers, _guard = fetched[-1]
        assert url.startswith(
            "https://gitlab.com/api/v4/projects/group%2Fproj/repository/archive.tar.gz?sha=main"
        )
        assert headers["Authorization"] == "Bearer glpat_T"

    def test_unsupported_host(self, rl, fetched):
        with pytest.raises(RuntimeError, match="not a supported archive host"):
            _make(rl.RepoLoader, repo_url="https://bitbucket.org/o/r")._obtain_repo()

    def test_direct_archive_url_is_downloaded_with_the_network_guard(self, rl, fetched):
        root, url, _ref, subdir = _make(
            rl.RepoLoader, repo_url="https://example.com/dl/repo.zip"
        )._obtain_repo()
        assert (url, subdir) == ("https://example.com/dl/repo.zip", "")
        assert fetched[-1][2] is True
        assert _repo_paths(rl, root) == ["m.py"]

    def test_http_archive_url_is_refused(self, rl, fetched):
        with pytest.raises(ValueError, match="https"):
            _make(rl.RepoLoader, repo_url="http://example.com/dl/repo.zip")._obtain_repo()


# --------------------------------------------------------------------------------------
# RepoLoader: downloads (SSRF guard, redirects, size cap)
# --------------------------------------------------------------------------------------
@pytest.fixture
def public_hosts(rl, monkeypatch):
    """files.example.org and cdn.example.org resolve to a public address; others resolve for real."""
    real = socket.getaddrinfo

    def fake(host, port, *args, **kwargs):
        if host in ("files.example.org", "cdn.example.org"):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 443))]
        return real(host, port, *args, **kwargs)

    monkeypatch.setattr(rl.socket, "getaddrinfo", fake)


def _mock_http(monkeypatch, handler):
    real_client = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw)
    )


class TestNetworkGuard:
    @pytest.mark.parametrize(
        "url",
        [
            "https://127.0.0.1/x.zip",
            "https://localhost/x.zip",
            "https://10.0.0.5/x.zip",
            "https://169.254.169.254/x.zip",
            "https://[::1]/x.zip",
        ],
    )
    def test_non_public_hosts_are_refused(self, rl, url):
        with pytest.raises(RuntimeError, match="not a public address"):
            rl._assert_public_https(url)

    def test_plain_http_is_refused(self, rl):
        with pytest.raises(RuntimeError, match="only https"):
            rl._assert_public_https("http://example.com/x.zip")

    def test_public_host_passes(self, rl, public_hosts):
        rl._assert_public_https("https://files.example.org/x.zip")

    def test_one_private_address_among_public_ones_is_refused(self, rl, monkeypatch):
        answers = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 443)),
        ]
        monkeypatch.setattr(rl.socket, "getaddrinfo", lambda *_a, **_k: answers)
        with pytest.raises(RuntimeError, match="not a public address"):
            rl._assert_public_https("https://rebind.example.org/x.zip")

    def test_internal_hosts_can_be_allowed_explicitly(self, rl, monkeypatch):
        monkeypatch.setenv("CODEWIKI_ALLOW_PRIVATE_HOSTS", "1")
        rl._assert_public_https("https://10.0.0.5/x.zip")

    def test_display_url_hides_credentials_and_query(self, rl):
        assert (
            rl._display_url("https://u:p@example.com/a/b.zip?sig=abc")
            == "https://example.com/a/b.zip"
        )


class TestFetch:
    def _fetch(self, rl, url, dest, headers=None):
        _make(rl.RepoLoader)._fetch(url, headers or {}, str(dest), guard=True)

    def test_downloads_the_body(self, rl, public_hosts, monkeypatch, tmp_path):
        _mock_http(monkeypatch, lambda _req: httpx.Response(200, content=b"zipbytes"))
        self._fetch(rl, "https://files.example.org/r.zip", tmp_path / "out")
        assert (tmp_path / "out").read_bytes() == b"zipbytes"

    def test_redirect_to_a_private_address_is_refused(
        self, rl, public_hosts, monkeypatch, tmp_path
    ):
        def handler(request):
            if request.url.host == "files.example.org":
                return httpx.Response(302, headers={"location": "https://10.0.0.5/x.zip"})
            raise AssertionError("the private address must never be requested")

        _mock_http(monkeypatch, handler)
        with pytest.raises(RuntimeError, match="not a public address"):
            self._fetch(rl, "https://files.example.org/r.zip", tmp_path / "out")

    def test_authorization_is_dropped_on_a_cross_host_redirect(
        self, rl, public_hosts, monkeypatch, tmp_path
    ):
        seen = {}

        def handler(request):
            seen[request.url.host] = request.headers.get("authorization")
            if request.url.host == "files.example.org":
                return httpx.Response(302, headers={"location": "https://cdn.example.org/r.zip"})
            return httpx.Response(200, content=b"zipbytes")

        _mock_http(monkeypatch, handler)
        self._fetch(
            rl, "https://files.example.org/r.zip", tmp_path / "out", {"Authorization": "Bearer t"}
        )
        assert seen == {"files.example.org": "Bearer t", "cdn.example.org": None}
        assert (tmp_path / "out").read_bytes() == b"zipbytes"

    def test_too_many_redirects(self, rl, public_hosts, monkeypatch, tmp_path):
        _mock_http(
            monkeypatch,
            lambda _req: httpx.Response(
                302, headers={"location": "https://files.example.org/r.zip"}
            ),
        )
        with pytest.raises(RuntimeError, match="redirects"):
            self._fetch(rl, "https://files.example.org/r.zip", tmp_path / "out")

    def test_http_error(self, rl, public_hosts, monkeypatch, tmp_path):
        _mock_http(monkeypatch, lambda _req: httpx.Response(404))
        with pytest.raises(RuntimeError, match="HTTP 404"):
            self._fetch(rl, "https://files.example.org/r.zip", tmp_path / "out")

    def test_download_size_cap(self, rl, public_hosts, monkeypatch, tmp_path):
        monkeypatch.setattr(rl, "MAX_DOWNLOAD_BYTES", 10)
        _mock_http(monkeypatch, lambda _req: httpx.Response(200, content=b"x" * 100))
        with pytest.raises(RuntimeError, match="larger than"):
            self._fetch(rl, "https://files.example.org/r.zip", tmp_path / "out")


# --------------------------------------------------------------------------------------
# RepoLoader: symbol extraction and import resolution
# --------------------------------------------------------------------------------------
class TestJavaSymbols:
    def test_declarations_and_methods(self, rl):
        symbols = {(s["symbol"], s["kind"]) for s in rl.extract_symbols(JAVA_SOURCE, "java")}
        assert symbols == {
            ("Hello", "class"),
            ("Hello.hi", "method"),
            ("Inner", "class"),
            ("Shape", "interface"),
            ("Color", "enum"),
            ("Pt", "record"),
        }

    def test_abstract_and_interface_methods_without_a_body_are_skipped(self, rl):
        names = {s["symbol"] for s in rl.extract_symbols(JAVA_SOURCE, "java")}
        assert "Hello.nope" not in names
        assert "Shape.area" not in names

    def test_line_spans(self, rl):
        spans = {
            s["symbol"]: (s["line_start"], s["line_end"])
            for s in rl.extract_symbols(JAVA_SOURCE, "java")
        }
        assert spans["Hello"] == (5, 13)
        assert spans["Hello.hi"] == (6, 8)
        assert spans["Inner"] == (10, 12)

    def test_imports(self, rl):
        assert rl.extract_imports(JAVA_SOURCE, "java") == ["org.y.Util"]

    def test_imports_resolve_under_any_source_root(self, rl):
        files = [
            {
                "repo_path": "mod/src/main/java/org/x/Hello.java",
                "language": "java",
                "text": JAVA_SOURCE,
                "is_doc": False,
            },
            {
                "repo_path": "mod/src/main/java/org/y/Util.java",
                "language": "java",
                "text": "package org.y;\npublic class Util {}\n",
                "is_doc": False,
            },
        ]
        index = rl.build_jvm_index(files)
        assert index["org.y.Util"] == ["mod/src/main/java/org/y/Util.java"]
        edges = rl.resolve_edges(rl.build_manifest(files))
        assert edges["mod/src/main/java/org/x/Hello.java"]["depends_on"] == [
            "mod/src/main/java/org/y/Util.java"
        ]
        assert edges["mod/src/main/java/org/y/Util.java"]["called_by"] == [
            "mod/src/main/java/org/x/Hello.java"
        ]


def _jf(path, text):
    return {"repo_path": path, "language": "java", "text": text, "is_doc": False}


class TestSamePackageEdges:
    FILES = [
        _jf(
            "svc/src/main/java/org/x/Base.java",
            "package org.x;\npublic class Base {}\n",
        ),
        _jf(
            "svc/src/main/java/org/x/Child.java",
            "package org.x;\n// Other is only in a comment\npublic class Child extends Base {}\n",
        ),
        _jf(
            "svc/src/main/java/org/x/Other.java",
            "package org.x;\npublic class Other {}\n",
        ),
        _jf(
            "svc/src/main/java/org/y/Far.java",
            "package org.y;\npublic class Far { Base b; }\n",
        ),
        _jf(
            "other/src/main/java/org/x/Base.java",
            "package org.x;\npublic class Base {}\n",
        ),
    ]

    def test_resolves_unqualified_type_in_same_package(self, rl):
        edges = rl.resolve_edges(rl.build_manifest(self.FILES))
        assert edges["svc/src/main/java/org/x/Child.java"]["depends_on"] == [
            "svc/src/main/java/org/x/Base.java"
        ]
        assert edges["svc/src/main/java/org/x/Base.java"]["called_by"] == [
            "svc/src/main/java/org/x/Child.java"
        ]

    def test_ignores_names_that_only_appear_in_comments(self, rl):
        edges = rl.resolve_edges(rl.build_manifest(self.FILES))
        assert (
            "svc/src/main/java/org/x/Other.java"
            not in edges["svc/src/main/java/org/x/Child.java"]["depends_on"]
        )

    def test_other_packages_and_other_modules_are_not_linked(self, rl):
        edges = rl.resolve_edges(rl.build_manifest(self.FILES))
        assert edges["svc/src/main/java/org/y/Far.java"]["depends_on"] == []
        assert (
            "other/src/main/java/org/x/Base.java"
            not in edges["svc/src/main/java/org/x/Child.java"]["depends_on"]
        )

    def test_does_not_duplicate_an_edge_that_has_an_import(self, rl):
        files = [
            _jf("m/src/A.java", "package p;\nimport p.B;\nclass A { B b; }\n"),
            _jf("m/src/B.java", "package p;\nclass B {}\n"),
        ]
        edges = rl.resolve_edges(rl.build_manifest(files))
        assert edges["m/src/A.java"]["depends_on"] == ["m/src/B.java"]

    def test_files_without_a_package_line_are_skipped(self, rl):
        files = [_jf("m/src/A.java", "class A { B b; }\n"), _jf("m/src/B.java", "class B {}\n")]
        assert rl.same_package_edges(files) == {}


class TestFeignEdges:
    YML = "spring:\n  application:\n    name: account-service\n"
    CONTROLLER = (
        'package a;\n@RestController\n@RequestMapping("/accounts")\npublic class AccountController {\n'
        "    @GetMapping\n    Object list() { return null; }\n"
        '    @PutMapping("/{id}")\n    Object put() { return null; }\n}\n'
    )
    CLIENT = (
        'package u;\n@FeignClient(name = "account-service", configuration = C.class)\n'
        "public interface AccountService {\n"
        '    @GetMapping("/accounts")\n    Object list();\n}\n'
    )

    def _files(self, client=None, yml=None):
        return [
            {
                "repo_path": "Account-Service/src/main/resources/application.yml",
                "language": "yaml",
                "text": yml or self.YML,
                "is_doc": False,
            },
            _jf("Account-Service/src/main/java/a/AccountController.java", self.CONTROLLER),
            _jf("User-Service/src/main/java/u/AccountService.java", client or self.CLIENT),
        ]

    def test_client_links_to_the_controller_serving_its_route(self, rl):
        edges = rl.resolve_edges(rl.build_manifest(self._files()))
        client = "User-Service/src/main/java/u/AccountService.java"
        controller = "Account-Service/src/main/java/a/AccountController.java"
        assert edges[client]["depends_on"] == [controller]
        assert edges[controller]["called_by"] == [client]

    def test_path_variables_match_whatever_their_name(self, rl):
        client = self.CLIENT.replace(
            '@GetMapping("/accounts")', '@PutMapping("/accounts/{accountId}")'
        )
        edges = rl.resolve_edges(rl.build_manifest(self._files(client=client)))
        assert edges["User-Service/src/main/java/u/AccountService.java"]["depends_on"] == [
            "Account-Service/src/main/java/a/AccountController.java"
        ]

    def test_no_edge_when_no_route_is_shared(self, rl):
        client = self.CLIENT.replace('@GetMapping("/accounts")', '@GetMapping("/elsewhere")')
        edges = rl.resolve_edges(rl.build_manifest(self._files(client=client)))
        assert edges["User-Service/src/main/java/u/AccountService.java"]["depends_on"] == []

    def test_no_edge_when_the_method_differs(self, rl):
        client = self.CLIENT.replace("@GetMapping", "@DeleteMapping")
        edges = rl.resolve_edges(rl.build_manifest(self._files(client=client)))
        assert edges["User-Service/src/main/java/u/AccountService.java"]["depends_on"] == []

    def test_no_edge_when_the_service_name_is_unknown(self, rl):
        client = self.CLIENT.replace("account-service", "nobody")
        edges = rl.resolve_edges(rl.build_manifest(self._files(client=client)))
        assert edges["User-Service/src/main/java/u/AccountService.java"]["depends_on"] == []

    def test_service_name_match_ignores_case(self, rl):
        yml = "spring:\n  application:\n    name: ACCOUNT-SERVICE\n"
        edges = rl.resolve_edges(rl.build_manifest(self._files(yml=yml)))
        assert edges["User-Service/src/main/java/u/AccountService.java"]["depends_on"] == [
            "Account-Service/src/main/java/a/AccountController.java"
        ]

    def test_repo_without_feign_clients_is_unchanged(self, rl):
        assert rl.feign_edges([_jf("m/src/A.java", "package p;\nclass A {}\n")]) == {}


class TestPythonAndJavaScript:
    def test_python_symbols_have_exact_spans(self, rl):
        source = "import os\nfrom .sib import x\nfrom pkg.mod import y\n\nclass A:\n    def m(self):\n        pass\n\nasync def top():\n    return 1\n"
        spans = {
            s["symbol"]: (s["kind"], s["line_start"], s["line_end"])
            for s in rl.extract_symbols(source, "python")
        }
        assert spans == {"A": ("class", 5, 7), "A.m": ("method", 6, 7), "top": ("function", 9, 10)}
        assert rl.extract_imports(source, "python") == ["os", ".sib", "pkg.mod"]

    def test_python_imports_resolve_to_repo_paths(self, rl):
        source = "import os\nfrom .sib import x\nfrom pkg.mod import y\n"
        files = [
            {"repo_path": "pkg/a.py", "language": "python", "text": source, "is_doc": False},
            {"repo_path": "pkg/sib.py", "language": "python", "text": "x = 1\n", "is_doc": False},
            {"repo_path": "pkg/mod.py", "language": "python", "text": "y = 1\n", "is_doc": False},
        ]
        edges = rl.resolve_edges(rl.build_manifest(files))
        assert edges["pkg/a.py"]["depends_on"] == ["pkg/mod.py", "pkg/sib.py"]
        assert edges["pkg/sib.py"]["called_by"] == ["pkg/a.py"]

    def test_javascript(self, rl):
        spans = {
            s["symbol"]: (s["kind"], s["line_start"], s["line_end"])
            for s in rl.extract_symbols(JS_SOURCE, "javascript")
        }
        assert spans == {"f": ("function", 3, 5), "K": ("class", 6, 10)}
        assert rl.extract_imports(JS_SOURCE, "javascript") == ["./a", "../b.js"]


def test_walk_files_applies_ignore_rules_and_subtree(rl, tmp_path):
    for rel, text in {
        "src/a.py": "x = 1\n",
        "src/pkg/b.py": "y = 1\n",
        "node_modules/m.js": "z = 1\n",
        "__pycache__/c.py": "w = 1\n",
        "logo.png": "binary",
        "empty.py": "   \n",
    }.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    assert [f["repo_path"] for f in rl.walk_files(tmp_path)] == ["src/a.py", "src/pkg/b.py"]
    assert [f["repo_path"] for f in rl.walk_files(tmp_path, ["src/pkg"])] == ["src/pkg/b.py"]
    assert len(rl.walk_files(tmp_path, max_files=1)) == 1


def test_load_repo_with_zero_files_explains_where_to_look(rl, tmp_path):
    (tmp_path / "logo.png").write_text("binary")
    with pytest.raises(RuntimeError, match="0 ingestible files"):
        _make(rl.RepoLoader, local_path=str(tmp_path)).load_repo()


# --------------------------------------------------------------------------------------
# CodeWikiBuilder
# --------------------------------------------------------------------------------------
STANDARD_TOP_LEVEL = {
    "filename",
    "mimetype",
    "export_format",
    "document_id",
    "connector_type",
    "source_url",
    "indexed_time",
    "text",
    "metadata",
}

WIKI_FIELDS = {
    "title",
    "content_kind",
    "wiki_kind",
    "repo_path",
    "language",
    "module",
    "wiki_summary",
    "symbol",
    "wiki_symbols",
    "wiki_depends_on",
    "wiki_called_by",
    "wiki_files",
    "repo_url",
    "repo_ref",
    "num_chunks",
    "wiki_markdown",
    "chunk_index",
}


def _page(**overrides):
    page = {
        "content_kind": "wiki_file_page",
        "repo_path": "src/pkg/foo.py",
        "title": "src/pkg/foo.py",
        "language": "python",
        "module": "src/pkg",
        "summary": "Foo helpers",
        "body": "Does things.",
        "symbols": [{"symbol": "Foo", "kind": "class", "line_start": 1, "line_end": 5}],
        "depends_on": ["src/pkg/bar.py"],
        "called_by": [],
    }
    page.update(overrides)
    return page


class TestPageToDocs:
    def test_wiki_fields_live_under_metadata_and_standard_fields_stay_top_level(self, builder):
        """The OpenRAG ingest callback keeps only standard top-level fields but passes `metadata` through."""
        docs = builder.page_to_docs(
            _page(), repo_url="https://github.com/o/r", repo_ref="main", chunk_size=3000
        )
        assert len(docs) == 1
        doc = docs[0]
        assert set(doc) == STANDARD_TOP_LEVEL
        assert WIKI_FIELDS <= set(doc["metadata"])
        assert doc["metadata"]["repo_path"] == "src/pkg/foo.py"
        assert doc["metadata"]["content_kind"] == "wiki_file_page"
        assert json.loads(doc["metadata"]["wiki_symbols"])[0]["line_start"] == 1
        assert json.loads(doc["metadata"]["wiki_depends_on"]) == ["src/pkg/bar.py"]

    def test_filename_and_source_url(self, builder):
        doc = builder.page_to_docs(
            _page(), repo_url="https://github.com/o/r/", repo_ref="dev", chunk_size=3000
        )[0]
        assert doc["filename"] == "src/pkg/foo.py"
        assert doc["source_url"] == "https://github.com/o/r/blob/dev/src/pkg/foo.py"
        assert doc["metadata"]["source_url"] == doc["source_url"]

    def test_symbol_pages_link_to_the_repo_not_a_file_path(self, builder):
        page = _page(
            content_kind="wiki_symbol_page",
            repo_path="a.py",
            symbol="Foo",
            line_start=3,
            line_end=9,
        )
        page["repo_path"] = "a.py :: Foo"
        doc = builder.page_to_docs(
            page, repo_url="https://github.com/o/r", repo_ref="", chunk_size=3000
        )[0]
        assert doc["source_url"] == "https://github.com/o/r"
        assert (doc["metadata"]["line_start"], doc["metadata"]["line_end"]) == (3, 9)

    def test_document_id_is_stable_and_distinct_per_page(self, builder):
        kwargs = {"repo_url": "https://github.com/o/r", "repo_ref": "main", "chunk_size": 3000}
        first = builder.page_to_docs(_page(), **kwargs)[0]["document_id"]
        again = builder.page_to_docs(_page(), **kwargs)[0]["document_id"]
        other = builder.page_to_docs(_page(repo_path="src/pkg/bar.py"), **kwargs)[0]["document_id"]
        assert first == again
        assert first != other

    def test_symbol_pages_do_not_share_the_file_pages_document_id(self, builder):
        kwargs = {"repo_url": "https://github.com/o/r", "repo_ref": "main", "chunk_size": 3000}
        file_page = _page()
        foo = _page(content_kind="wiki_symbol_page", symbol="Foo", line_start=1, line_end=5)
        bar = _page(content_kind="wiki_symbol_page", symbol="Bar", line_start=7, line_end=9)
        ids = [builder.page_to_docs(p, **kwargs)[0]["document_id"] for p in (file_page, foo, bar)]
        assert len(set(ids)) == 3

    def test_overloaded_symbols_get_distinct_document_ids(self, builder):
        kwargs = {"repo_url": "https://github.com/o/r", "repo_ref": "main", "chunk_size": 3000}
        first = _page(content_kind="wiki_symbol_page", symbol="run", line_start=3)
        second = _page(content_kind="wiki_symbol_page", symbol="run", line_start=20)
        a = builder.page_to_docs(first, **kwargs)[0]["document_id"]
        b = builder.page_to_docs(second, **kwargs)[0]["document_id"]
        assert a != b

    def test_file_page_document_id_is_unchanged(self, builder):
        """Only symbol pages gained a new identity; existing file-page ids must not move."""
        import hashlib

        doc = builder.page_to_docs(
            _page(), repo_url="https://github.com/o/r", repo_ref="main", chunk_size=3000
        )[0]
        expected = hashlib.sha1(b"https://github.com/o/r@main:src/pkg/foo.py").hexdigest()
        assert doc["document_id"] == expected

    def test_source_url_uses_head_when_the_ref_is_unknown(self, builder):
        doc = builder.page_to_docs(
            _page(), repo_url="https://github.com/o/r", repo_ref="", chunk_size=3000
        )[0]
        assert doc["source_url"] == "https://github.com/o/r/blob/HEAD/src/pkg/foo.py"

    def test_long_pages_are_split_and_every_chunk_carries_the_header(self, builder):
        body = "\n".join(f"line {i}" for i in range(400))
        docs = builder.page_to_docs(_page(body=body), repo_url="", repo_ref="", chunk_size=500)
        assert len(docs) > 1
        assert [d["metadata"]["chunk_index"] for d in docs] == list(range(len(docs)))
        assert {d["metadata"]["num_chunks"] for d in docs} == {len(docs)}
        header = "# [src/pkg/foo.py] src/pkg/foo.py"
        assert all(d["text"].startswith(header) for d in docs)
        rebuilt = "".join(d["metadata"]["wiki_markdown"] for d in docs)
        assert rebuilt == builder.render_page_text(_page(body=body))


class TestChunkFragments:
    def test_short_text_is_a_single_fragment(self, builder):
        assert builder.chunk_fragments("abc\n", 100) == ["abc\n"]

    def test_non_positive_size_disables_splitting(self, builder):
        assert builder.chunk_fragments("a\nb\n", 0) == ["a\nb\n"]

    def test_splitting_is_lossless_and_respects_the_size(self, builder):
        text = "".join(f"line number {i}\n" for i in range(200))
        frags = builder.chunk_fragments(text, 120)
        assert "".join(frags) == text
        assert all(len(f) <= 120 for f in frags)

    def test_a_line_that_fits_is_never_split(self, builder):
        text = "".join(f"line number {i}\n" for i in range(50))
        frags = builder.chunk_fragments(text, 100)
        assert all(f.endswith("\n") for f in frags)

    def test_an_oversized_line_is_cut_at_the_size(self, builder):
        frags = builder.chunk_fragments("short\n" + "x" * 250 + "\nend\n", 100)
        assert "".join(frags) == "short\n" + "x" * 250 + "\nend\n"
        assert all(len(f) <= 100 for f in frags)


def _source_file(path, n_lines):
    """A Python file with exactly `n_lines` lines (no trailing newline) and one function."""
    lines = ["def f():"] + ["    x = 1"] * (n_lines - 1)
    return {"repo_path": path, "language": "python", "text": "\n".join(lines), "is_doc": False}


def _symbol_pages(builder, rl, n_lines, **kwargs):
    files = [_source_file("a.py", n_lines)]
    manifest = rl.build_manifest(files)
    edges = rl.resolve_edges(manifest)
    pages = builder.build_pages(files, manifest, edges, **kwargs)
    return [p for p in pages if p["content_kind"] == "wiki_symbol_page"]


class TestSymbolPageThreshold:
    def test_default_is_50_lines(self, builder, rl):
        assert _symbol_pages(builder, rl, 49) == []
        assert [p["symbol"] for p in _symbol_pages(builder, rl, 50)] == ["f"]

    def test_explicit_threshold(self, builder, rl):
        assert _symbol_pages(builder, rl, 60, symbol_page_min_lines=100) == []
        assert len(_symbol_pages(builder, rl, 60, symbol_page_min_lines=60)) == 1

    def test_documentation_files_never_get_symbol_pages(self, builder, rl):
        files = [
            {
                "repo_path": "README.md",
                "language": "markdown",
                "text": "# T\n" * 100,
                "is_doc": True,
            }
        ]
        manifest = rl.build_manifest(files)
        pages = builder.build_pages(files, manifest, rl.resolve_edges(manifest))
        assert {p["content_kind"] for p in pages} == {"wiki_overview", "wiki_doc_page"}

    @pytest.mark.parametrize("value", [0, None])
    def test_zero_or_empty_in_the_component_falls_back_to_50(self, builder, rl, value):
        def build(n_lines):
            files = [_source_file("a.py", n_lines)]
            manifest = rl.build_manifest(files)
            comp = _make(
                builder.CodeWikiBuilder,
                repo_data={
                    "repo": {
                        "files": files,
                        "manifest": manifest,
                        "edges": rl.resolve_edges(manifest),
                    }
                },
                use_llm=False,
                symbol_page_min_lines=value,
            )
            return [d.data["metadata"]["content_kind"] for d in comp.build_docs()]

        assert "wiki_symbol_page" not in build(49)
        assert "wiki_symbol_page" in build(50)


class TestBuilderComponent:
    def test_deterministic_build_without_a_model(self, builder, rl):
        files = [_source_file("pkg/a.py", 10)]
        manifest = rl.build_manifest(files)
        comp = _make(
            builder.CodeWikiBuilder,
            repo_data={
                "repo": {
                    "files": files,
                    "manifest": manifest,
                    "edges": rl.resolve_edges(manifest),
                    "repo_url": "https://github.com/o/r",
                    "repo_ref": "main",
                }
            },
            model=None,
        )
        docs = [d.data for d in comp.build_docs()]
        kinds = {d["metadata"]["content_kind"] for d in docs}
        assert kinds == {"wiki_overview", "wiki_module_page", "wiki_file_page"}
        assert all(d["metadata"]["repo_url"] == "https://github.com/o/r" for d in docs)

    def test_missing_repo_payload_is_a_clear_error(self, builder):
        with pytest.raises(RuntimeError, match="no repo payload"):
            _make(builder.CodeWikiBuilder, repo_data=None).build_docs()


# --------------------------------------------------------------------------------------
# CodeWikiSearch / CodeWikiReader / CodeWikiDeps: shared query helpers
# --------------------------------------------------------------------------------------
TOOLS = [("search", "CodeWikiSearch"), ("reader", "CodeWikiReader"), ("deps", "CodeWikiDeps")]


@pytest.mark.parametrize(("fixture", "cls"), TOOLS)
class TestSharedHelpers:
    def test_term_any_matches_top_level_and_metadata_fields(self, request, fixture, cls):
        component = getattr(request.getfixturevalue(fixture), cls)
        clause = component._term_any("repo_path", "a.py")["bool"]
        assert clause["minimum_should_match"] == 1
        assert [next(iter(c["term"])) for c in clause["should"]] == [
            "repo_path",
            "repo_path.keyword",
            "metadata.repo_path",
            "metadata.repo_path.keyword",
        ]
        assert all(c["term"][next(iter(c["term"]))] == "a.py" for c in clause["should"])

    def test_term_any_with_a_list_uses_terms(self, request, fixture, cls):
        component = getattr(request.getfixturevalue(fixture), cls)
        clause = component._term_any("content_kind", ["a", "b"])["bool"]["should"]
        assert len(clause) == 4
        assert all("terms" in c for c in clause)

    def test_flatten_merges_metadata_without_overwriting_top_level_values(
        self, request, fixture, cls
    ):
        component = getattr(request.getfixturevalue(fixture), cls)
        flat = component._flatten(
            {
                "filename": "kept.md",
                "language": "",
                "metadata": {"filename": "ignored.md", "language": "python", "repo_path": "a.py"},
            }
        )
        assert flat["filename"] == "kept.md"
        assert flat["language"] == "python"
        assert flat["repo_path"] == "a.py"

    def test_flatten_falls_back_to_frontmatter_in_the_text(self, request, fixture, cls):
        component = getattr(request.getfixturevalue(fixture), cls)
        text = "# [src/a.py] src/a.py\n---\ncontent_kind: wiki_file_page\nrepo_path: src/a.py\n---\n\nbody"
        flat = component._flatten({"text": text})
        assert flat["repo_path"] == "src/a.py"
        assert flat["content_kind"] == "wiki_file_page"

    def test_flatten_falls_back_to_the_header_line(self, request, fixture, cls):
        component = getattr(request.getfixturevalue(fixture), cls)
        assert component._flatten({"text": "# [src/a.py] title\nbody"})["repo_path"] == "src/a.py"

    def test_basic_auth_falls_back_to_the_environment(self, request, fixture, cls, monkeypatch):
        component = _make(getattr(request.getfixturevalue(fixture), cls))
        monkeypatch.setenv("OPENSEARCH_PASSWORD", "from-env")
        assert component._build_auth_kwargs() == {"http_auth": ("admin", "from-env")}

    def test_jwt_mode_without_a_token_is_an_error(self, request, fixture, cls):
        component = _make(
            getattr(request.getfixturevalue(fixture), cls), auth_mode="jwt", jwt_token=""
        )
        with pytest.raises(ValueError, match="no jwt_token"):
            component._build_auth_kwargs()

    def test_jwt_header_and_bearer_prefix(self, request, fixture, cls):
        component = _make(
            getattr(request.getfixturevalue(fixture), cls),
            auth_mode="jwt",
            jwt_token="tok",
            bearer_prefix=True,
        )
        assert component._build_auth_kwargs() == {"headers": {"Authorization": "Bearer tok"}}

    def test_url_and_index_fall_back_to_the_environment(self, request, fixture, cls, monkeypatch):
        component = _make(getattr(request.getfixturevalue(fixture), cls))
        assert component._resolve_url() == "https://opensearch:9200"
        assert component._index() == "documents"
        monkeypatch.setenv("OPENSEARCH_URL", "https://os.internal:9200")
        monkeypatch.setenv("OPENSEARCH_INDEX_NAME", "wiki")
        assert component._resolve_url() == "https://os.internal:9200"
        assert component._index() == "wiki"

    @pytest.mark.parametrize("value", ["ADMIN", "ADMIN123!", "DOCUMENTS", "MY_SECRET"])
    def test_all_uppercase_values_are_kept_as_real_values(
        self, request, fixture, cls, value, monkeypatch
    ):
        component = _make(
            getattr(request.getfixturevalue(fixture), cls),
            username=value,
            password=value,
            index_name=value,
        )
        monkeypatch.setenv("OPENSEARCH_USERNAME", "from-env")
        monkeypatch.setenv("OPENSEARCH_PASSWORD", "from-env")
        monkeypatch.setenv("OPENSEARCH_INDEX_NAME", "from-env")
        assert component._build_auth_kwargs() == {"http_auth": (value, value)}
        assert component._index() == value

    def test_the_env_var_name_defaults_still_resolve_from_the_environment(
        self, request, fixture, cls, monkeypatch
    ):
        component = _make(getattr(request.getfixturevalue(fixture), cls))
        monkeypatch.setenv("OPENSEARCH_URL", "https://os.internal:9200")
        monkeypatch.setenv("OPENSEARCH_INDEX_NAME", "wiki")
        assert component.opensearch_url == "OPENSEARCH_URL"
        assert component._resolve_url() == "https://os.internal:9200"
        assert component._index() == "wiki"


# --------------------------------------------------------------------------------------
# CodeWikiSearch
# --------------------------------------------------------------------------------------
class _FakeIndices:
    def __init__(self, mapping):
        self._mapping = mapping

    def get_mapping(self, index):
        return self._mapping


class _FakeSearchClient:
    def __init__(self, hits, mapping=None):
        self.hits = hits
        self.indices = _FakeIndices(mapping or {})
        self.bodies = []

    def search(self, index, body):
        self.bodies.append(body)
        return {"hits": {"hits": self.hits}}


class _Embedding:
    def embed_query(self, _text):
        return [0.1, 0.2]


class TestCodeWikiSearch:
    HIT = {
        "_score": 1.5,
        "_source": {
            "text": "# [src/a.py] src/a.py\nbody",
            "filename": "uploaded.txt",
            "metadata": {
                "repo_path": "src/a.py",
                "content_kind": "wiki_file_page",
                "language": "python",
                "module": "src",
                "wiki_summary": "Does A",
                "wiki_symbols": json.dumps([{"symbol": "A", "line_start": 1, "line_end": 4}]),
                "source_url": "https://github.com/o/r/blob/main/src/a.py",
                "line_start": 1,
                "line_end": 4,
            },
        },
    }

    def _component(self, search, monkeypatch, **attrs):
        client = _FakeSearchClient(
            [self.HIT],
            mapping={
                "documents": {
                    "mappings": {
                        "properties": {"chunk_embedding_m": {"type": "knn_vector", "dimension": 2}}
                    }
                }
            },
        )
        comp = _make(search.CodeWikiSearch, embedding=_Embedding(), **attrs)
        monkeypatch.setattr(comp, "_client", lambda: client)
        return comp, client

    def test_results_keep_provenance_and_render_in_the_chat_ui(self, search, monkeypatch):
        comp, _client = self._component(search, monkeypatch, query="how does A work")
        results = comp.search()
        assert len(results) == 1
        data = results[0].data
        assert data["filename"] == "src/a.py"
        assert data["text"].startswith("# [src/a.py]")
        assert (data["repo_path"], data["content_kind"], data["language"]) == (
            "src/a.py",
            "wiki_file_page",
            "python",
        )
        assert data["summary"] == "Does A"
        assert data["symbols"][0]["symbol"] == "A"
        assert (data["line_start"], data["line_end"]) == (1, 4)
        assert data["source_url"] == "https://github.com/o/r/blob/main/src/a.py"

    def test_query_is_hybrid_knn_plus_keyword(self, search, monkeypatch):
        comp, client = self._component(search, monkeypatch, query="how does A work", top_k=3)
        comp.search()
        body = client.bodies[0]
        should = body["query"]["bool"]["should"]
        assert body["size"] == 3
        assert should[0]["dis_max"]["boost"] == 0.7
        assert should[0]["dis_max"]["queries"][0]["knn"]["chunk_embedding_m"]["vector"] == [
            0.1,
            0.2,
        ]
        assert should[1]["multi_match"]["boost"] == 0.3
        assert body["query"]["bool"]["filter"] == []
        assert "chunk_embedding*" in body["_source"]["excludes"]

    def test_content_kind_filter(self, search, monkeypatch):
        comp, client = self._component(
            search, monkeypatch, query="x", content_kind="wiki_symbol_page"
        )
        comp.search()
        (flt,) = client.bodies[0]["query"]["bool"]["filter"]
        assert flt["bool"]["should"][0] == {"term": {"content_kind": "wiki_symbol_page"}}

    def test_vector_fields_with_another_dimension_are_ignored(self, search):
        comp = _make(search.CodeWikiSearch)
        client = _FakeSearchClient(
            [],
            mapping={
                "documents": {
                    "mappings": {
                        "properties": {"chunk_embedding_a": {"type": "knn_vector", "dimension": 3}}
                    }
                }
            },
        )
        assert comp._knn_fields(client, [0.1, 0.2]) == []

    def test_empty_query(self, search):
        results = _make(search.CodeWikiSearch, query="  ").search()
        assert results.data["results"] == []
        assert "Empty query" in results.data["error"]

    def test_embedding_failure_is_reported_not_raised(self, search):
        class Broken:
            def embed_query(self, _text):
                raise RuntimeError("model down")

        result = _make(search.CodeWikiSearch, query="x", embedding=Broken()).search()
        assert "Embedding failed" in result.data["error"]

    def test_opensearch_failure_is_reported_not_raised(self, search, monkeypatch):
        comp, client = self._component(search, monkeypatch, query="x")

        def boom(index, body):
            raise RuntimeError("cluster down")

        client.search = boom
        assert "OpenSearch query failed" in comp.search().data["error"]


# --------------------------------------------------------------------------------------
# CodeWikiReader
# --------------------------------------------------------------------------------------
def _chunk(repo_path, index, markdown, symbol="", kind="wiki_file_page", **extra):
    return {
        "text": f"chunk {index}",
        "metadata": {
            "repo_path": repo_path,
            "symbol": symbol,
            "content_kind": kind,
            "chunk_index": index,
            "wiki_markdown": markdown,
            "wiki_summary": "Summary",
            "wiki_symbols": json.dumps([{"symbol": "A", "line_start": 1, "line_end": 4}]),
            "wiki_depends_on": json.dumps(["b.py"]),
            "wiki_called_by": json.dumps(["c.py"]),
            **extra,
        },
    }


class _PagesClient:
    """Answers the reader's three kinds of query from an in-memory page store."""

    def __init__(self, pages):
        self.pages = pages
        self.bodies = []

    def search(self, index, body):
        self.bodies.append(body)
        wanted_symbol = '"symbol"' in json.dumps(body["query"])
        chunks = [c for c in self.pages if bool(c["metadata"]["symbol"]) == wanted_symbol]
        if body["size"] == 500:  # reassembly: every chunk of the page, in arbitrary order
            return {"hits": {"hits": [{"_source": c} for c in reversed(chunks)]}}
        return {"hits": {"hits": [{"_source": chunks[0]}] if chunks else []}}


class TestCodeWikiReader:
    FILE_CHUNKS = [
        _chunk("src/a.py", 0, "AAA\n", wiki_files=json.dumps([])),
        _chunk("src/a.py", 1, "BBB\n"),
        _chunk("src/a.py", 2, "CCC\n"),
    ]
    SYMBOL_CHUNKS = [
        _chunk(
            "src/a.py",
            0,
            "SYMBOL BODY\n",
            symbol="A.m",
            kind="wiki_symbol_page",
            wiki_source="def m(): ...",
            line_start=6,
            line_end=7,
        )
    ]

    def _read(self, reader, monkeypatch, reference, pages):
        comp = _make(reader.CodeWikiReader, reference=reference)
        monkeypatch.setattr(comp, "_client", lambda: _PagesClient(pages))
        return comp.read_page()

    def test_chunks_are_reassembled_in_order(self, reader, monkeypatch):
        (item,) = self._read(reader, monkeypatch, "src/a.py", self.FILE_CHUNKS)
        assert item.data["text"] == "AAA\nBBB\nCCC\n"
        assert item.data["filename"] == "src/a.py"
        assert item.data["symbols"][0]["line_end"] == 4
        assert item.data["depends_on"] == ["b.py"]
        assert item.data["called_by"] == ["c.py"]

    def test_symbol_reference(self, reader, monkeypatch):
        (item,) = self._read(
            reader, monkeypatch, "src/a.py :: A.m", self.FILE_CHUNKS + self.SYMBOL_CHUNKS
        )
        assert item.data["filename"] == "src/a.py :: A.m"
        assert item.data["text"] == "SYMBOL BODY\n"
        assert item.data["source"] == "def m(): ..."
        assert (item.data["line_start"], item.data["line_end"]) == (6, 7)

    def test_brackets_and_quotes_around_a_reference_are_ignored(self, reader, monkeypatch):
        (item,) = self._read(reader, monkeypatch, "[`src/a.py`]", self.FILE_CHUNKS)
        assert item.data["text"] == "AAA\nBBB\nCCC\n"

    def test_empty_reference(self, reader):
        (item,) = _make(reader.CodeWikiReader, reference="  ").read_page()
        assert "No page reference" in item.data["text"]
        assert "filename" in item.data

    def test_unknown_page(self, reader, monkeypatch):
        (item,) = self._read(reader, monkeypatch, "missing.py", [])
        assert "No wiki page found" in item.data["text"]
        assert item.data["filename"] == "missing.py"

    def test_repo_overview_reference_keeps_its_double_colon(self, reader, monkeypatch):
        overview = _chunk("repo::r", 0, "OVERVIEW\n", kind="wiki_overview")
        comp = _make(reader.CodeWikiReader, reference="repo::r")
        client = _PagesClient([overview])
        monkeypatch.setattr(comp, "_client", lambda: client)
        (item,) = comp.read_page()
        assert item.data["filename"] == "repo::r"
        assert item.data["text"] == "OVERVIEW\n"
        assert item.data["content_kind"] == "wiki_overview"
        first_query = json.dumps(client.bodies[0]["query"])
        assert '"repo::r"' in first_query
        assert '"symbol"' not in first_query  # not split into repo_path "repo" + symbol "r"

    def test_file_page_query_excludes_symbol_pages(self, reader, monkeypatch):
        comp = _make(reader.CodeWikiReader)
        client = _PagesClient(self.FILE_CHUNKS)
        monkeypatch.setattr(comp, "_client", lambda: client)
        comp._fetch_chunks("src/a.py", "")
        query = client.bodies[0]["query"]["bool"]
        assert "wiki_symbol_page" in json.dumps(query["must_not"])

    def test_symbol_page_query_does_not_exclude_symbol_pages(self, reader, monkeypatch):
        comp = _make(reader.CodeWikiReader)
        client = _PagesClient(self.SYMBOL_CHUNKS)
        monkeypatch.setattr(comp, "_client", lambda: client)
        comp._fetch_chunks("src/a.py", "A.m")
        assert client.bodies[0]["query"]["bool"]["must_not"] == []


# --------------------------------------------------------------------------------------
# CodeWikiDeps
# --------------------------------------------------------------------------------------
def _dep_page(repo_path, depends_on=(), called_by=(), summary=""):
    return {
        "text": f"# [{repo_path}] {repo_path}",
        "metadata": {
            "repo_path": repo_path,
            "content_kind": "wiki_file_page",
            "chunk_index": 0,
            "wiki_summary": summary or f"Summary of {repo_path}",
            "wiki_depends_on": json.dumps(list(depends_on)),
            "wiki_called_by": json.dumps(list(called_by)),
            "wiki_symbols": json.dumps(
                [{"symbol": "f", "kind": "function", "line_start": 1, "line_end": 3}]
            ),
        },
    }


class _GraphClient:
    def __init__(self, pages):
        self.pages = {p["metadata"]["repo_path"]: p for p in pages}

    def search(self, index, body):
        wanted = body["query"]["bool"]["must"][0]["bool"]["should"][0]["term"]["repo_path"]
        page = self.pages.get(wanted)
        return {"hits": {"hits": [{"_source": page}] if page else []}}


GRAPH = [
    _dep_page("a.py", depends_on=["b.py", "c.py"], called_by=["z.py"]),
    _dep_page("b.py", depends_on=["d.py"], called_by=["a.py"]),
    _dep_page("c.py", called_by=["a.py"]),
    _dep_page("d.py", called_by=["b.py"]),
    _dep_page("z.py", depends_on=["a.py"]),
]


class TestCodeWikiDeps:
    def _walk(self, deps, monkeypatch, **attrs):
        comp = _make(deps.CodeWikiDeps, **attrs)
        monkeypatch.setattr(comp, "_client", lambda: _GraphClient(GRAPH))
        return [item.data for item in comp.walk()]

    def test_every_item_has_filename_and_text(self, deps, monkeypatch):
        """OpenRAG's chat UI drops tool results without them ("Found 0 results")."""
        items = self._walk(deps, monkeypatch, repo_path="a.py")
        assert items
        assert all(item.get("filename") and item.get("text") for item in items)

    def test_first_item_lists_both_directions(self, deps, monkeypatch):
        items = self._walk(deps, monkeypatch, repo_path="a.py")
        origin = items[0]
        assert origin["relation"] == "origin"
        assert "depends_on (2): b.py, c.py" in origin["text"]
        assert "called_by (1): z.py" in origin["text"]
        assert (origin["depends_on"], origin["called_by"]) == (["b.py", "c.py"], ["z.py"])

    def test_direct_neighbours(self, deps, monkeypatch):
        items = self._walk(deps, monkeypatch, repo_path="a.py")
        assert {(i["repo_path"], i["relation"]) for i in items[1:]} == {
            ("b.py", "depends_on"),
            ("c.py", "depends_on"),
            ("z.py", "called_by"),
        }
        neighbour = next(i for i in items if i["repo_path"] == "b.py")
        assert "a.py → imports b.py" in neighbour["text"]
        assert "f:1-3" in neighbour["text"]

    def test_direction_limits_the_neighbours_but_not_the_origin_report(self, deps, monkeypatch):
        items = self._walk(deps, monkeypatch, repo_path="a.py", direction="depends_on")
        assert {i["repo_path"] for i in items[1:]} == {"b.py", "c.py"}
        assert "called_by (1): z.py" in items[0]["text"]

    def test_hops_follow_edges_transitively(self, deps, monkeypatch):
        items = self._walk(deps, monkeypatch, repo_path="a.py", hops=2)
        hop2 = next(i for i in items if i["repo_path"] == "d.py")
        assert (hop2["hop"], hop2["via"]) == (2, "b.py")
        assert items[0]["edges"] is not None

    def test_hops_are_bounded_to_three(self, deps, monkeypatch):
        items = self._walk(deps, monkeypatch, repo_path="a.py", hops=99)
        assert items[0]["hops"] == 3

    def test_max_neighbours(self, deps, monkeypatch):
        items = self._walk(deps, monkeypatch, repo_path="a.py", max_nodes=1)
        assert len(items) == 2

    def test_unknown_origin(self, deps, monkeypatch):
        (item,) = self._walk(deps, monkeypatch, repo_path="missing.py")
        assert "No wiki page found" in item["text"]
        assert item["filename"] == "missing.py"

    def test_empty_origin(self, deps, monkeypatch):
        (item,) = self._walk(deps, monkeypatch, repo_path=" ")
        assert "No repo_path" in item["text"]
        assert "filename" in item

    def test_failing_root_fetch_is_reported_not_raised(self, deps, monkeypatch):
        comp = _make(deps.CodeWikiDeps, repo_path="a.py")

        def boom():
            raise RuntimeError("cluster down")

        monkeypatch.setattr(comp, "_client", boom)
        (item,) = [i.data for i in comp.walk()]
        assert "OpenSearch query failed" in item["text"]
        assert item["error"] == item["text"]
        assert item["filename"] == "a.py"

    def test_failing_neighbour_fetch_does_not_drop_the_traversal(self, deps, monkeypatch):
        class FlakyClient(_GraphClient):
            def search(self, index, body):
                wanted = body["query"]["bool"]["must"][0]["bool"]["should"][0]["term"]["repo_path"]
                if wanted == "b.py":
                    raise RuntimeError("shard unavailable")
                return super().search(index, body)

        comp = _make(deps.CodeWikiDeps, repo_path="a.py", hops=2)
        monkeypatch.setattr(comp, "_client", lambda: FlakyClient(GRAPH))
        items = [i.data for i in comp.walk()]
        by_path = {i["repo_path"]: i for i in items}
        assert by_path["a.py"]["relation"] == "origin"
        assert by_path["c.py"]["found"] is True
        assert by_path["b.py"]["found"] is False
        assert "d.py" not in by_path  # b.py's own edges are unreadable, so the walk stops there
