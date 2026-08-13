"""Central source of truth for all OpenRAG container image references.

Purpose
-------
This module defines every container image the OpenRAG stack uses.  It is the
single place to change registry, organisation, or image names — all other code
imports from here.

Changing image coordinates
--------------------------
Three environment variables control where images are pulled from:

* ``IMAGE_REGISTRY`` — container registry host (default: ``"docker.io"``).
* ``IMAGE_ORG``      — namespace / organisation within the registry
  (default: ``"langflowai"``).
* ``OPENRAG_VERSION`` / ``OPENRAG_IMAGE_TAG`` — set in the project ``.env``
  file (read by Docker Compose) to pin a specific version tag.  Do **not**
  hard-code versions here.

Allow-list usage
----------------
`all_openrag_repos` returns every repository path that OpenRAG owns.
``container_manager.py`` calls it inside ``ContainerManager.__init__`` (after
loading the TUI ``.env``) to build ``self._openrag_image_repos``.
``startup_checks._is_openrag_repository`` calls it at invocation time.
Both approaches ensure that ``IMAGE_REGISTRY`` / ``IMAGE_ORG`` overrides set
in ``~/.openrag/tui/.env`` are always reflected.  **If you add, rename, or
remove an image here, both callers stay in sync automatically.**

Multi-arch manifests
--------------------
All images are assumed to be multi-arch fat manifests.  No per-architecture
tag suffix is needed or supported.
"""

import os
import subprocess

# ---------------------------------------------------------------------------
# Registry & organisation
# ---------------------------------------------------------------------------


def get_registry() -> str:
    """Return the container registry host, reading ``os.environ`` at call time.

    Defaults to ``"docker.io"``.  Override via the ``IMAGE_REGISTRY``
    environment variable (or ``~/.openrag/tui/.env``).

    Empty falls back to the default, matching Compose's
    ``${IMAGE_REGISTRY:-docker.io}``.
    """
    return os.environ.get("IMAGE_REGISTRY") or "docker.io"


def get_org() -> str:
    """Return the registry organisation / namespace, reading ``os.environ`` at call time.

    Defaults to ``"langflowai"``.  Override via the ``IMAGE_ORG``
    environment variable (or ``~/.openrag/tui/.env``).

    Empty falls back to the default, matching Compose's
    ``${IMAGE_ORG:-langflowai}``.
    """
    return os.environ.get("IMAGE_ORG") or "langflowai"


# ---------------------------------------------------------------------------
# Image names
# ---------------------------------------------------------------------------

IMAGE_NAME_BACKEND: str = "openrag-backend"
IMAGE_NAME_FRONTEND: str = "openrag-frontend"
IMAGE_NAME_LANGFLOW: str = "openrag-langflow"
IMAGE_NAME_OPENSEARCH: str = "openrag-opensearch"
IMAGE_NAME_DASHBOARDS: str = "openrag-dashboards"

#: All OpenRAG-owned image short names.
OPENRAG_IMAGE_NAMES: tuple[str, ...] = (
    IMAGE_NAME_BACKEND,
    IMAGE_NAME_FRONTEND,
    IMAGE_NAME_LANGFLOW,
    IMAGE_NAME_OPENSEARCH,
    IMAGE_NAME_DASHBOARDS,
)

#: Third-party images referenced in the compose stack (used for cleanup
#: allow-listing).
THIRD_PARTY_IMAGE_REPOS: tuple[str, ...] = (
    "langflow/langflow",
    "opensearchproject/opensearch",
    "opensearchproject/opensearch-dashboards",
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def image_repo(name: str) -> str:
    """Return the fully-qualified repository path (without tag) for *name*.

    Reads :envvar:`IMAGE_REGISTRY` and :envvar:`IMAGE_ORG` from
    ``os.environ`` at *call time* so that values set (or overridden) by a
    ``.env`` file after module import are always reflected.

    Example::

        image_repo("openrag-backend")
        # -> "docker.io/langflowai/openrag-backend"
    """
    return f"{get_registry()}/{get_org()}/{name}"


def image_ref(name: str, version: str = "latest") -> str:
    """Return the fully-qualified image reference including tag.

    Args:
        name:    Short image name (e.g. ``"openrag-backend"``).
        version: Version / tag string (e.g. ``"0.5.1"`` or ``"latest"``).

    Example::

        image_ref("openrag-backend", "0.5.1")
        # -> "docker.io/langflowai/openrag-backend:0.5.1"
    """
    return f"{image_repo(name)}:{version}"


def all_openrag_repos() -> tuple[str, ...]:
    """Return the set of all OpenRAG-owned repository paths (no tag).

    Includes both the fully-qualified path (``registry/org/name``) and the
    short path without a registry prefix (``org/name``) so that callers can
    match images already present locally under either form.

    Reads ``IMAGE_REGISTRY`` and ``IMAGE_ORG`` from ``os.environ`` at call
    time — snapshots them once so each env lookup happens exactly once per
    call regardless of how many image names are in ``OPENRAG_IMAGE_NAMES``.
    """
    registry = get_registry()
    org = get_org()
    standard = tuple(f"{registry}/{org}/{n}" for n in OPENRAG_IMAGE_NAMES)
    # Short form (e.g. "langflowai/openrag-backend") for matching locally-
    # pulled images that may omit the registry prefix.
    short = tuple(f"{org}/{n}" for n in OPENRAG_IMAGE_NAMES)
    return standard + short + THIRD_PARTY_IMAGE_REPOS


# ---------------------------------------------------------------------------
# Registry reachability validation
# ---------------------------------------------------------------------------


class ImageNotFoundError(Exception):
    """Raised when the image or tag does not exist in the registry."""


class RegistryUnreachableError(Exception):
    """Raised when the registry host cannot be reached (DNS/network failure)."""


class RegistryAuthError(Exception):
    """Raised when the registry returns an authentication failure (401/403)."""


class MalformedImageRefError(Exception):
    """Raised when the image reference cannot be parsed by the runtime."""


def validate_image_reachable(image_ref: str, runtime: str = "docker") -> None:
    """Test whether *image_ref* exists in its registry without downloading layers.

    Uses ``<runtime> manifest inspect`` (a metadata-only call) so no image
    data is transferred.

    Args:
        image_ref: Fully-resolved image reference, e.g.
                   ``"docker.io/langflowai/openrag-backend:0.5.1"``.
        runtime:   Container runtime executable name.  Defaults to
                   ``"docker"``; pass ``"podman"`` for Podman.

    Raises:
        :exc:`MalformedImageRefError`:    The reference could not be parsed.
        :exc:`ImageNotFoundError`:        The image or tag is absent from the
                                          registry.
        :exc:`RegistryAuthError`:         The registry rejected the request
                                          with a 401 or 403.
        :exc:`RegistryUnreachableError`:  The registry host could not be
                                          reached (DNS/network failure).
    """
    # Reject obviously malformed references before hitting the network.
    if not image_ref or image_ref.startswith(":") or " " in image_ref:
        raise MalformedImageRefError(
            f"Image reference is malformed and cannot be parsed: {image_ref!r}"
        )

    try:
        result = subprocess.run(
            [runtime, "manifest", "inspect", image_ref],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError as exc:
        raise RegistryUnreachableError(f"Container runtime {runtime!r} not found on PATH.") from exc
    except subprocess.TimeoutExpired as exc:
        raise RegistryUnreachableError(f"Timed out contacting registry for {image_ref!r}.") from exc

    if result.returncode == 0:
        return  # Image exists — all good.

    combined = (result.stdout + result.stderr).lower()

    # Authentication failures
    if any(
        token in combined
        for token in ("unauthorized", "denied", "403", "401", "authentication", "forbidden")
    ):
        raise RegistryAuthError(
            f"Authentication failure accessing {image_ref!r}: {(result.stderr or result.stdout).strip()}"
        )

    # DNS / network failures
    if any(
        token in combined
        for token in (
            "no such host",
            "name resolution",
            "dial tcp",
            "connection refused",
            "network is unreachable",
            "i/o timeout",
            "lookup",
            "tls",
            "certificate",
        )
    ):
        raise RegistryUnreachableError(
            f"Registry unreachable for {image_ref!r}: {(result.stderr or result.stdout).strip()}"
        )

    # Malformed reference reported by the runtime
    if any(
        token in combined
        for token in (
            "invalid reference",
            "invalid image",
            "invalid tag",
            "could not parse",
            "malformed",
        )
    ):
        raise MalformedImageRefError(
            f"Image reference {image_ref!r} could not be parsed: {(result.stderr or result.stdout).strip()}"
        )

    # Default: image / tag not found
    raise ImageNotFoundError(
        f"Image {image_ref!r} not found in registry: {(result.stderr or result.stdout).strip()}"
    )
