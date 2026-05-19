"""JWT-sourced role assignment.

Reads the role claim named by `OPENRAG_JWT_ROLES_CLAIM` from a decoded JWT
and maps each claim value to a built-in OpenRAG role via the
`OPENRAG_ROLE_CLAIM_*` settings.

Pure helper — no DB access. All env vars are read on each call so test
overrides (`monkeypatch.setenv`) take effect without process restart.
"""

from __future__ import annotations

import os

from services.rbac_service import is_rbac_enforced
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _claim_to_role_map() -> dict[str, list[str]]:
    """Build a {jwt_claim_value: [openrag_role, ...]} map from current env.

    Constructed per call so test overrides are picked up. Skips unset
    mappings entirely.
    """
    pairs = (
        ("admin", os.getenv("OPENRAG_ROLE_CLAIM_ADMIN", "admin")),
        ("developer", os.getenv("OPENRAG_ROLE_CLAIM_DEVELOPER", "manager")),
        ("user", os.getenv("OPENRAG_ROLE_CLAIM_USER", "user")),
        ("viewer", os.getenv("OPENRAG_ROLE_CLAIM_VIEWER")),
    )
    mapping: dict[str, list[str]] = {}
    for openrag_role, claim_value in pairs:
        if not claim_value:
            continue
        mapping.setdefault(claim_value, []).append(openrag_role)
    return mapping


def extract_jwt_role_names(claims: dict | None) -> list[str]:
    """Return the OpenRAG role names derived from a decoded JWT.

    Returns an empty list when the claim is missing, malformed, or contains
    no recognized role values. The returned list preserves the order of the
    JWT claim and is de-duplicated.
    """
    if not claims:
        return []

    claim_name = os.getenv("OPENRAG_JWT_ROLES_CLAIM", "openrag_roles")
    raw = claims.get(claim_name)
    if raw is None:
        return []

    if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
        logger.warning(
            "JWT roles claim is not a list of strings; treating as no roles",
            claim_name=claim_name,
            value_type=type(raw).__name__,
        )
        return []

    mapping = _claim_to_role_map()
    seen: set[str] = set()
    result: list[str] = []
    for value in raw:
        openrag_roles = mapping.get(value)
        if not openrag_roles:
            logger.debug("Unknown JWT role claim value ignored", value=value)
            continue
        for role in openrag_roles:
            if role not in seen:
                seen.add(role)
                result.append(role)
    return result


def jwt_roles_enabled() -> bool:
    """True when JWT-sourced role assignment is active.

    Tied to RBAC enforcement today; kept as its own predicate so the two
    can be decoupled later if needed.
    """
    return is_rbac_enforced()
