import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_operator_settings(monkeypatch):
    """Importing the host loads the developer's .env into os.environ. Operator
    settings it may hold (the insecure-HTTP opt-in, the origin allowlist, a CA
    bundle) must not leak into these tests, which set exactly what each case
    needs."""
    for name in [name for name in os.environ if name.startswith("OPENRAG_SHAREPOINT_")]:
        monkeypatch.delenv(name)
