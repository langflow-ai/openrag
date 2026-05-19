"""The OPENRAG_RBAC_UI_ENABLED default flips with OPENRAG_RUN_MODE.

  * saas / on_prem -> default "false" (platform IdP owns role management)
  * anything else  -> default "true"

An explicit OPENRAG_RBAC_UI_ENABLED always wins — operators can flip the
local admin UI back on in saas / on_prem for one-off debugging.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.settings import _resolve_rbac_ui_default  # noqa: E402


@pytest.mark.parametrize(
    "run_mode, expected",
    [
        ("", "true"),  # unset -> oss path
        ("oss", "true"),
        ("OSS", "true"),
        ("saas", "false"),
        ("SaaS", "false"),
        ("on_prem", "false"),
        ("ON_PREM", "false"),
        ("unknown-mode", "true"),  # unrecognised falls back to oss
    ],
)
def test_default_resolves_from_run_mode(monkeypatch, run_mode, expected):
    if run_mode:
        monkeypatch.setenv("OPENRAG_RUN_MODE", run_mode)
    else:
        monkeypatch.delenv("OPENRAG_RUN_MODE", raising=False)
    assert _resolve_rbac_ui_default() == expected
