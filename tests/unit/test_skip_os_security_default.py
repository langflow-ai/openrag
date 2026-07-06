"""The OPENRAG_SKIP_OS_SECURITY_SETUP default flips with OPENRAG_RUN_MODE.

  * saas / on_prem (CPD) -> default "true"  (platform owns security context)
  * anything else        -> default "false" (today's behaviour)

An explicit OPENRAG_SKIP_OS_SECURITY_SETUP always wins.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config.settings import _resolve_skip_os_security_default  # noqa: E402


@pytest.mark.parametrize(
    "run_mode, expected",
    [
        ("", "false"),  # unset -> default oss path
        ("oss", "false"),
        ("OSS", "false"),
        ("saas", "true"),
        ("SaaS", "true"),
        ("on_prem", "true"),
        ("ON_PREM", "true"),
        ("unknown-mode", "false"),  # unrecognised falls back to false
    ],
)
def test_default_resolves_from_run_mode(monkeypatch, run_mode, expected):
    if run_mode:
        monkeypatch.setenv("OPENRAG_RUN_MODE", run_mode)
    else:
        monkeypatch.delenv("OPENRAG_RUN_MODE", raising=False)
    assert _resolve_skip_os_security_default() == expected
