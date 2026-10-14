"""The opensearch healthcheck may only read variables its container receives (#1411)."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

# ``$$NAME`` / ``$${NAME}`` survive compose interpolation as ``$NAME`` and are
# expanded by the shell inside the container, so they resolve against the
# service's own ``environment`` rather than the host's ``.env``.
CONTAINER_VAR = re.compile(r"\$\$\{?([A-Za-z_][A-Za-z0-9_]*)")


def _healthcheck_container_vars(service: dict) -> set[str]:
    test = service["healthcheck"]["test"]
    command = test if isinstance(test, str) else " ".join(test)
    return set(CONTAINER_VAR.findall(command))


def _environment_names(service: dict) -> set[str]:
    environment = service.get("environment") or {}
    if isinstance(environment, dict):
        return set(environment)
    return {str(entry).split("=", 1)[0] for entry in environment}


def test_opensearch_healthcheck_only_reads_variables_passed_to_the_container():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    opensearch = compose["services"]["opensearch"]

    # The image and its entrypoint wrapper export no credentials, so anything
    # missing here expands to an empty string and the check never passes.
    missing = _healthcheck_container_vars(opensearch) - _environment_names(opensearch)
    assert not missing, (
        f"opensearch healthcheck reads {sorted(missing)}, "
        "which the service's environment does not define"
    )
