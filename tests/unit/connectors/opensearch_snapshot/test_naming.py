from __future__ import annotations

import re

import pytest

from connectors.opensearch_snapshot import naming
from connectors.opensearch_snapshot.naming import NamingError


def test_slug_format_and_uniqueness():
    slugs = {naming.new_slug() for _ in range(200)}
    assert len(slugs) == 200
    assert all(re.fullmatch(r"[a-z][a-z0-9]{9}", s) for s in slugs)
    assert all(naming.is_valid_slug(s) for s in slugs)


@pytest.mark.parametrize(
    "bad", ["", "1abcdefghi", "abcdefghi", "abcdefghijk", "Abcdefghij", "abc-efghij", None]
)
def test_invalid_slugs(bad):
    assert not naming.is_valid_slug(bad)
    with pytest.raises(NamingError):
        naming.alias_name(bad, 0)


def test_physical_names_are_opaque():
    slug = "abcdefghij"
    assert naming.alias_name(slug, 2) == "ds_abcdefghij_2"
    assert naming.concrete_name(slug, 2, 3) == "ds_abcdefghij_2_g3"
    assert naming.slug_pattern(slug) == "ds_abcdefghij_*"
    assert naming.role_name(slug) == "openrag_ds_abcdefghij"
    assert naming.repo_name(slug, 3) == "openrag_stage_abcdefghij_g3"


@pytest.mark.parametrize("ordinal", [-1, True, "1", 1.5])
def test_invalid_ordinal(ordinal):
    with pytest.raises(NamingError):
        naming.alias_name("abcdefghij", ordinal)


@pytest.mark.parametrize(
    "name",
    [
        "documents",
        "orag-x",
        "knowledge_filters",
        "documents_x",
        "my_documents_idx",
        "api_keys",
        "openrag_dls_principals",
    ],
)
def test_existing_role_patterns_are_rejected(name):
    with pytest.raises(NamingError):
        naming.assert_outside_user_patterns(name)


def test_generated_names_pass():
    naming.assert_outside_user_patterns(naming.alias_name("abcdefghij", 0))
    naming.assert_outside_user_patterns(naming.concrete_name("abcdefghij", 12, 1))


def test_every_generated_slug_pattern_is_outside_existing_roles():
    for _ in range(50):
        slug = naming.new_slug()
        naming.assert_outside_user_patterns(naming.concrete_name(slug, 0, 1))


def test_reads_both_role_files(monkeypatch, tmp_path):
    (tmp_path / "securityconfig").mkdir()
    (tmp_path / "cloud_securityconfig").mkdir()
    (tmp_path / "securityconfig/roles.yml").write_text(
        "_meta: {type: roles}\nr1:\n  index_permissions:\n    - index_patterns: ['alpha*']\n"
        "openrag_ds_zzz:\n  index_permissions:\n    - index_patterns: ['ds_*']\n"
    )
    (tmp_path / "cloud_securityconfig/roles.yml").write_text(
        "r2:\n  index_permissions:\n    - index_patterns: ['beta?', '/re[0-9]+/']\n"
    )
    monkeypatch.setattr(naming, "_REPO_ROOT", tmp_path)
    naming._user_patterns.cache_clear()
    try:
        with pytest.raises(NamingError):
            naming.assert_outside_user_patterns("alpha1")  # file 1
        with pytest.raises(NamingError):
            naming.assert_outside_user_patterns("beta9")  # file 2
        with pytest.raises(NamingError):
            naming.assert_outside_user_patterns("re42")  # regex pattern
        naming.assert_outside_user_patterns("ds_abcdefghij_0")  # openrag_ds_* roles are exempt
    finally:
        naming._user_patterns.cache_clear()


def test_fails_closed_without_role_files(monkeypatch, tmp_path):
    monkeypatch.setattr(naming, "_REPO_ROOT", tmp_path)
    naming._user_patterns.cache_clear()
    try:
        with pytest.raises(NamingError):
            naming.assert_outside_user_patterns("ds_abcdefghij_0")
    finally:
        naming._user_patterns.cache_clear()
