"""Tests for the `INSTANA_SECRETS` default value (`.env.example`).

Regression for discussion_r3864664254: the Makefile `include`s and `export`s
every `.env` line as GNU Make syntax (see Makefile's ENV_FILE loading), which
treats a bare `$` as a Make variable reference. A `^name$`-anchored regex
value silently loses its `$` (and the following comma) under `make backend` /
`make dev`, so `q`/`search`/`filename` were never actually redacted despite
the tracer reporting no error. The fixed default anchors with `\\Z` instead of
`$`, which is `re.match()`-equivalent (the tracer already anchors at the
start of the string) and contains no `$` for Make to mangle.
"""

import re

import pytest

instana_secrets = pytest.importorskip("instana.util.secrets")

# Mirrors the INSTANA_SECRETS default in .env.example / docker-compose.yml /
# kubernetes/helm/bomarag/values.yaml / kubernetes/operator's env.go.
INSTANA_SECRETS_DEFAULT = "regex:.*key.*,.*pass.*,.*secret.*,.*token.*,q\\Z,search\\Z,filename\\Z"


def _kwlist():
    matcher, names = INSTANA_SECRETS_DEFAULT.split(":", 1)
    assert matcher == "regex"
    return names.split(",")


def test_default_contains_no_dollar_sign():
    """A `$` here is silently corrupted by the Makefile's `.env` include/export."""
    assert "$" not in INSTANA_SECRETS_DEFAULT


@pytest.mark.parametrize("name", ["q", "search", "filename", "api_key", "auth_token"])
def test_default_redacts_the_documented_query_parameters(name):
    assert instana_secrets.contains_secret(name, "regex", _kwlist()) is True


@pytest.mark.parametrize("name", ["quantity", "research", "filename2", "myfilename"])
def test_default_does_not_over_redact_similarly_named_parameters(name):
    """Exact-match names must not swallow unrelated parameters that merely
    contain the same substring — this is what \\Z (vs. a bare `contains`
    match) buys us, same as the original `^name$` intent."""
    assert not instana_secrets.contains_secret(name, "regex", _kwlist())


def test_default_matches_the_makefile_include_export_round_trip():
    """Guards the actual bug: simulates GNU Make's variable-reference parsing
    of a `$`-anchored value to show why it breaks, and confirms the current
    `\\Z`-anchored default has nothing for that parsing to corrupt."""

    def make_mangled(value: str) -> str:
        # `$X` where X is a single character is a Make variable reference;
        # an undefined one expands to "". A trailing lone `$` is literal.
        return re.sub(r"\$(.)", "", value)

    old_style_default = "regex:.*key.*,.*pass.*,.*secret.*,.*token.*,^q$,^search$,^filename$"
    assert make_mangled(old_style_default) != old_style_default

    assert make_mangled(INSTANA_SECRETS_DEFAULT) == INSTANA_SECRETS_DEFAULT
