"""Image configuration for OpenRAG container images."""

import os

# ---------------------------------------------------------------------------
# Registry & organisation
# ---------------------------------------------------------------------------

#: Container registry host.  Override via IMAGE_REGISTRY env var.
#: Default matches the current Docker Hub images.
IMAGE_REGISTRY: str = os.getenv("IMAGE_REGISTRY", "docker.io")

#: Organisation / namespace within the registry.  Override via IMAGE_ORG.
IMAGE_ORG: str = os.getenv("IMAGE_ORG", "langflowai")

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

    Example::

        image_repo("openrag-backend")
        # -> "docker.io/langflowai/openrag-backend"
    """
    return f"{IMAGE_REGISTRY}/{IMAGE_ORG}/{name}"


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

    Includes both the standard path and the legacy path without a registry
    prefix so that callers can match images already present locally under
    either form.
    """
    standard = tuple(image_repo(n) for n in OPENRAG_IMAGE_NAMES)
    # Short form (e.g. "langflowai/openrag-backend") for matching locally-
    # pulled images that may omit the registry prefix.
    short = tuple(f"{IMAGE_ORG}/{n}" for n in OPENRAG_IMAGE_NAMES)
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
    except FileNotFoundError:
        raise RegistryUnreachableError(
            f"Container runtime {runtime!r} not found on PATH."
        )
    except subprocess.TimeoutExpired:
        raise RegistryUnreachableError(
            f"Timed out contacting registry for {image_ref!r}."
        )

    if result.returncode == 0:
        return  # Image exists — all good.

    combined = (result.stdout + result.stderr).lower()

    # Authentication failures
    if any(token in combined for token in ("unauthorized", "denied", "403", "401",
                                            "authentication", "forbidden")):
        raise RegistryAuthError(
            f"Authentication failure accessing {image_ref!r}: {(result.stderr or result.stdout).strip()}"
        )

    # DNS / network failures
    if any(token in combined for token in ("no such host", "name resolution",
                                            "dial tcp", "connection refused",
                                            "network is unreachable", "i/o timeout",
                                            "lookup", "tls", "certificate")):
        raise RegistryUnreachableError(
            f"Registry unreachable for {image_ref!r}: {(result.stderr or result.stdout).strip()}"
        )

    # Malformed reference reported by the runtime
    if any(token in combined for token in ("invalid reference", "invalid image",
                                            "invalid tag", "could not parse",
                                            "malformed")):
        raise MalformedImageRefError(
            f"Image reference {image_ref!r} could not be parsed: {(result.stderr or result.stdout).strip()}"
        )

    # Default: image / tag not found
    raise ImageNotFoundError(
        f"Image {image_ref!r} not found in registry: {(result.stderr or result.stdout).strip()}"
    )
