"""Unit test for the OCI credential env-var block in
``config.settings.AppClients.patched_async_client`` (mirrors the existing
WatsonX block).

Uses a real ``AppClients()`` instance (not the process-wide ``clients``
singleton) so this doesn't leak state into other tests. The embedding
provider is set to "oci" (not "openai"), which makes the property skip its
HTTP/2 probe (`if provider.lower() == "openai": ... else: use_http2 =
False`) -- so this exercises the real property end-to-end with no network
calls at all.
"""

import os
from types import SimpleNamespace

import pytest

from config.settings import AppClients


def _fake_config():
    return SimpleNamespace(
        providers=SimpleNamespace(
            openai=SimpleNamespace(api_key=""),
            anthropic=SimpleNamespace(api_key=""),
            watsonx=SimpleNamespace(api_key="", endpoint="", project_id=""),
            ollama=SimpleNamespace(endpoint=""),
            oci=SimpleNamespace(
                user="ocid1.user.oc1..xxx",
                fingerprint="xx:xx:xx:xx",
                tenancy="ocid1.tenancy.oc1..xxx",
                compartment_id="ocid1.compartment.oc1..xxx",
                key="",
                key_file="/tmp/oci_key.pem",
                region="us-ashburn-1",
            ),
        ),
        knowledge=SimpleNamespace(
            embedding_model="cohere.embed-multilingual-v3.0",
            embedding_provider="oci",
        ),
    )


@pytest.fixture(autouse=True)
def _isolated_environ():
    """Snapshot/restore ``os.environ`` around each test.

    ``patched_async_client`` writes credentials straight to ``os.environ``
    (not via ``monkeypatch``) as a real side effect of the property under
    test — including an ``OPENAI_API_KEY=no-key-required`` dummy-key
    fallback unrelated to OCI. ``monkeypatch.delenv``/``setenv`` only
    reverts changes monkeypatch itself made, so without this snapshot those
    writes would leak into every test that runs afterward in the same
    session. Also clears the OCI_* vars up front so a real local ``.env``
    can't make the "unset field is omitted" assertions flaky.
    """
    original = dict(os.environ)
    for var in (
        "OCI_USER",
        "OCI_FINGERPRINT",
        "OCI_TENANCY",
        "OCI_COMPARTMENT_ID",
        "OCI_KEY_FILE",
        "OCI_KEY",
        "OCI_REGION",
    ):
        os.environ.pop(var, None)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def test_patched_async_client_sets_oci_env_vars_from_config(monkeypatch):
    monkeypatch.setattr("config.settings.get_openrag_config", lambda: _fake_config())

    app_clients = AppClients()
    client = app_clients.patched_async_client

    assert client is not None
    assert os.environ["OCI_USER"] == "ocid1.user.oc1..xxx"
    assert os.environ["OCI_FINGERPRINT"] == "xx:xx:xx:xx"
    assert os.environ["OCI_TENANCY"] == "ocid1.tenancy.oc1..xxx"
    assert os.environ["OCI_COMPARTMENT_ID"] == "ocid1.compartment.oc1..xxx"
    assert os.environ["OCI_KEY_FILE"] == "/tmp/oci_key.pem"
    assert os.environ["OCI_REGION"] == "us-ashburn-1"
    assert "OCI_KEY" not in os.environ


def test_patched_async_client_skips_unset_oci_fields(monkeypatch):
    config = _fake_config()
    config.providers.oci.region = ""
    monkeypatch.setattr("config.settings.get_openrag_config", lambda: config)

    app_clients = AppClients()
    _ = app_clients.patched_async_client

    assert "OCI_REGION" not in os.environ
