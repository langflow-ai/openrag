"""Compose healthchecks may only read variables their container receives (#1411)."""

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
BASE = "docker-compose.yml"

# ``$$NAME`` / ``$${NAME}`` survive compose interpolation as ``$NAME`` and are
# expanded by the shell inside the container, so they resolve against the
# service's own ``environment`` rather than the host's ``.env``.
CONTAINER_VAR = re.compile(r"\$\$\{?([A-Za-z_][A-Za-z0-9_]*)")


def _load_services(name: str) -> dict:
    compose = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))
    return compose.get("services") or {}


def _environment(service: dict) -> dict:
    environment = service.get("environment") or {}
    if isinstance(environment, dict):
        return dict(environment)
    return dict(str(entry).partition("=")[::2] for entry in environment)


def _merge(base: dict, override: dict) -> dict:
    # Mirrors how ``docker compose -f base -f override`` combines a service for
    # the keys checked here: ``environment`` merges by name, and the
    # healthcheck's own keys merge, with the override winning.
    merged = {**base, **override}
    merged["environment"] = {**_environment(base), **_environment(override)}
    if "healthcheck" in base or "healthcheck" in override:
        merged["healthcheck"] = {
            **(base.get("healthcheck") or {}),
            **(override.get("healthcheck") or {}),
        }
    return merged


def _healthchecked_services():
    """Yield (stack, service name, effective service) for every healthcheck.

    Override files only hold the keys they change and are always layered on
    top of the base file, so they are checked as the merged service rather
    than on their own. Services an override leaves alone are already covered
    by the base file.
    """
    base_services = _load_services(BASE)
    for name, service in base_services.items():
        if "healthcheck" in service:
            yield BASE, name, _merge(service, {})

    for path in sorted(ROOT.glob("docker-compose*.yml")):
        if path.name == BASE:
            continue
        for name, override in _load_services(path.name).items():
            merged = _merge(base_services.get(name) or {}, override or {})
            if "healthcheck" in merged:
                yield f"{BASE} + {path.name}", name, merged


CASES = list(_healthchecked_services())


def _healthcheck_container_vars(service: dict) -> set[str]:
    test = service["healthcheck"].get("test") or []
    command = test if isinstance(test, str) else " ".join(test)
    return set(CONTAINER_VAR.findall(command))


def test_discovery_finds_the_opensearch_healthcheck():
    # Guards against the parametrization below silently collecting nothing.
    assert (BASE, "opensearch") in {(stack, name) for stack, name, _ in CASES}


@pytest.mark.parametrize(
    ("stack", "name", "service"),
    CASES,
    ids=[f"{stack}::{name}" for stack, name, _ in CASES],
)
def test_healthcheck_only_reads_variables_passed_to_the_container(stack, name, service):
    # Variables from ``env_file`` are not counted: those files are
    # host-specific and not in the repo, so a healthcheck has to rely on
    # variables the compose file passes through ``environment`` explicitly.
    # Anything missing expands to an empty string and the check never passes.
    missing = _healthcheck_container_vars(service) - set(service["environment"])
    assert not missing, (
        f"{name} healthcheck in {stack} reads {sorted(missing)}, "
        "which the service's environment does not define"
    )
