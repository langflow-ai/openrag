"""Regression coverage: every OCI_* env var the backend reads must actually be
plumbed through by the three deployment surfaces that ship OpenRAG.

``ConfigManager._load_env_overrides`` reads 8 ``OCI_*`` variables to seed
``providers.oci``, but reading them only helps if the process is started with
them set:

  * ``docker-compose.yml`` has no ``env_file:`` directive, so ONLY the names
    explicitly listed in ``openrag-backend``'s ``environment:`` block reach the
    backend container. Anything missing there is silently unset no matter what
    the operator put in ``.env`` -- exactly how the WatsonX trio
    (``WATSONX_API_KEY``/``WATSONX_ENDPOINT``/``WATSONX_PROJECT_ID``) is
    handled, and the pattern these assertions mirror.
  * The Helm chart renders the backend's ``.env`` from
    ``templates/backend/backend-dotenv.yaml``.
  * The operator seeds the backend's ``.env`` from the
    ``DefaultOpenRagBEEnvVars`` map in ``internal/controller/env.go``.

The expected set is derived from ``config_manager.py`` itself rather than
hardcoded, so adding a 9th OCI env override without wiring it up fails here.
"""

import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_CONFIG_MANAGER = _REPO_ROOT / "src/config/config_manager.py"
_DOCKER_COMPOSE = _REPO_ROOT / "docker-compose.yml"
_HELM_BACKEND_DOTENV = _REPO_ROOT / "kubernetes/helm/openrag/templates/backend/backend-dotenv.yaml"
_HELM_VALUES = _REPO_ROOT / "kubernetes/helm/openrag/values.yaml"
_OPERATOR_ENV_GO = _REPO_ROOT / "kubernetes/operator/internal/controller/env.go"


def _oci_env_var_names() -> set[str]:
    """The OCI_* names ``_load_env_overrides`` actually reads."""
    source = _CONFIG_MANAGER.read_text(encoding="utf-8")
    names = set(re.findall(r'os\.getenv\("(OCI_[A-Z_]+)"\)', source))
    # Guard the guard: if the extraction ever silently matches nothing, the
    # per-surface assertions below would all vacuously pass.
    assert len(names) == 8, f"expected 8 OCI_* env overrides, found {sorted(names)}"
    return names


def _compose_backend_environment() -> set[str]:
    compose = yaml.safe_load(_DOCKER_COMPOSE.read_text(encoding="utf-8"))
    environment = compose["services"]["openrag-backend"]["environment"]
    # docker-compose list form: "NAME=${NAME}" entries.
    return {entry.split("=", 1)[0] for entry in environment}


def test_compose_has_no_env_file_directive_for_the_backend():
    """The premise of this module: nothing but ``environment:`` reaches the
    backend. If an ``env_file:`` is ever added, these assertions become
    stricter than necessary -- but they must be revisited deliberately."""
    compose = yaml.safe_load(_DOCKER_COMPOSE.read_text(encoding="utf-8"))
    assert "env_file" not in compose["services"]["openrag-backend"]


def test_watsonx_reference_pattern_is_present_in_compose():
    """Sanity-check the pattern the OCI assertion mirrors."""
    environment = _compose_backend_environment()
    assert {"WATSONX_API_KEY", "WATSONX_ENDPOINT", "WATSONX_PROJECT_ID"} <= environment


@pytest.mark.parametrize("name", sorted(_oci_env_var_names()))
def test_compose_passes_oci_env_var_to_backend(name):
    environment = _compose_backend_environment()
    assert name in environment, (
        f"{name} is read by ConfigManager._load_env_overrides but never passed "
        f"into openrag-backend's environment: block in docker-compose.yml"
    )


@pytest.mark.parametrize("name", sorted(_oci_env_var_names()))
def test_helm_backend_dotenv_renders_oci_env_var(name):
    template = _HELM_BACKEND_DOTENV.read_text(encoding="utf-8")
    assert f"{name}=" in template, (
        f"{name} is missing from the Helm backend .env template "
        f"({_HELM_BACKEND_DOTENV.relative_to(_REPO_ROOT)})"
    )


def test_helm_values_expose_the_oci_provider_block():
    values = yaml.safe_load(_HELM_VALUES.read_text(encoding="utf-8"))
    oci = values["llmProviders"]["oci"]
    assert set(oci) == {
        "enabled",
        "authMethod",
        "user",
        "fingerprint",
        "tenancy",
        "key",
        "keyFile",
        "compartmentId",
        "region",
    }


@pytest.mark.parametrize("name", sorted(_oci_env_var_names()))
def test_operator_backend_env_defaults_declare_oci_env_var(name):
    source = _OPERATOR_ENV_GO.read_text(encoding="utf-8")
    assert f'"{name}"' in source, (
        f"{name} is missing from DefaultOpenRagBEEnvVars in "
        f"{_OPERATOR_ENV_GO.relative_to(_REPO_ROOT)}"
    )
