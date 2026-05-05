from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt

from config.settings import is_no_auth_mode


def _dedupe_non_empty(values: list[str | None]) -> tuple[str, ...]:
    ordered = []
    for value in values:
        normalized = (value or "").strip()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    return tuple(ordered)


def _decode_claims_without_verification(jwt_token: str | None) -> dict[str, Any]:
    if not jwt_token:
        return {}

    raw_token = jwt_token.removeprefix("Bearer ").strip()
    if not raw_token:
        return {}

    try:
        return jwt.decode(
            raw_token,
            options={
                "verify_signature": False,
                "verify_aud": False,
                "verify_exp": False,
            },
        )
    except Exception:
        return {}


def _extract_groups(claims: dict[str, Any]) -> tuple[str, ...]:
    group_values: list[str | None] = []
    for claim_name in ("groups", "allowed_groups", "cognito:groups"):
        claim_value = claims.get(claim_name)
        if isinstance(claim_value, str):
            group_values.append(claim_value)
        elif isinstance(claim_value, list):
            group_values.extend(
                value for value in claim_value if isinstance(value, str)
            )
    return _dedupe_non_empty(group_values)


@dataclass(frozen=True)
class KnowledgeAccessContext:
    user_id: str | None = None
    user_email: str | None = None
    jwt_token: str | None = None
    groups: tuple[str, ...] = ()
    no_auth_mode: bool = False

    @property
    def principals(self) -> tuple[str, ...]:
        return _dedupe_non_empty([self.user_id, self.user_email])

    @property
    def enforce_acl(self) -> bool:
        return not self.no_auth_mode


def build_access_context(
    *,
    user_id: str | None = None,
    user_email: str | None = None,
    jwt_token: str | None = None,
    session_manager=None,
) -> KnowledgeAccessContext:
    claims = _decode_claims_without_verification(jwt_token)
    resolved_user_id = (
        user_id
        or claims.get("user_id")
        or claims.get("sub")
    )
    resolved_user_email = user_email or claims.get("email") or claims.get("preferred_username")

    if session_manager and resolved_user_id:
        user = session_manager.get_user(resolved_user_id)
        if user and not resolved_user_email:
            resolved_user_email = getattr(user, "email", None)

    return KnowledgeAccessContext(
        user_id=resolved_user_id,
        user_email=resolved_user_email,
        jwt_token=jwt_token,
        groups=_extract_groups(claims),
        no_auth_mode=is_no_auth_mode(),
    )
