"""JWT-sourced role assignment.

Reads the role claim named by `OPENRAG_JWT_ROLES_CLAIM` from a decoded JWT
and maps each claim value to a built-in OpenRAG role via the
`OPENRAG_ROLE_CLAIM_*` settings.

Pure helper — no DB access. Config is read through the per-call accessors in
`config.settings` so test overrides (`monkeypatch.setenv`) take effect without
a process restart.
"""

from __future__ import annotations

from config.settings import (
    get_jwt_roles_claim,
    get_role_claim_admin,
    get_role_claim_developer,
    get_role_claim_user,
    get_role_claim_viewer,
)
from services.rbac_service import is_rbac_enforced
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _claim_to_role_map() -> dict[str, list[str]]:
    """Build a {jwt_claim_value: [openrag_role, ...]} map from current env.

    Constructed per call so test overrides are picked up. Skips unset
    mappings entirely.
    """
    pairs = (
        ("admin", get_role_claim_admin()),
        ("developer", get_role_claim_developer()),
        ("user", get_role_claim_user()),
        ("viewer", get_role_claim_viewer()),
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

    claim_name = get_jwt_roles_claim()
    raw = claims.get(claim_name)
    if raw is None:
        logger.debug(
            "JWT roles claim absent",
            claim_name=claim_name,
            available_claim_keys=list(claims.keys()),
        )
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
    logger.debug(
        "JWT roles resolved",
        claim_name=claim_name,
        resolved_roles=result,
        mapping_keys=list(mapping.keys()),
    )
    return result


def jwt_roles_enabled() -> bool:
    """True when JWT-sourced role assignment is active.

    Tied to RBAC enforcement today; kept as its own predicate so the two
    can be decoupled later if needed.
    """
    return is_rbac_enforced()
