"""SQL user identity cache for authenticated requests.

The request auth surface carries external OAuth subjects in ``User.user_id``.
RBAC and ownership tables use the internal SQL ``users.id``. This module owns
that translation, including the per-process cache and first-login race lock.
"""

import asyncio

from cachetools import TTLCache
from fastapi import HTTPException

from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)

# Maps composite "{provider}:{subject}" -> SQL users.id. Doubles as the
# "we've already ensured a DB row for this user" cache so we don't pay
# the round-trip on every authenticated request. Cleared on user/role
# mutations via the rbac service invalidation hook.
#
# Necessary because legacy-migrated rows have id == user_id while older
# Phase-1 new rows had id == uuid4(); permission lookups need the SQL id,
# not the OAuth subject.
#
# The key is composite (provider, subject), NOT just user_id, because the
# OAuth subject string alone is not unique across providers — e.g. the
# synthetic `AnonymousUser` (provider="none", user_id="anonymous") must
# not collide with a hypothetical real user whose IdP issued the same
# subject string. Identity in this codebase is the (provider, subject)
# pair (see `ensure_user_row` and the `(oauth_provider, oauth_subject)`
# UNIQUE constraint on the users table).
_ENSURED_USER_IDS: TTLCache[str, str] = TTLCache(maxsize=4096, ttl=300)

# Per-(provider, subject) asyncio.Lock used to serialize concurrent
# first-time `_ensure_db_user` calls for the SAME identity. Without
# this, two requests racing through the cache miss → INSERT path both
# observe an empty users table, both attempt INSERT, and the second
# fails with `UNIQUE constraint failed: users.email_lookup_hash`. The
# lock is scoped per-identity so unrelated logins never block each
# other (and so two providers issuing the same subject string don't
# share a lock).
_ENSURE_LOCKS: dict[str, asyncio.Lock] = {}


def _user_cache_key(user: User) -> str:
    """Composite cache/lock key for a `User`.

    Mirrors the (oauth_provider, oauth_subject) UNIQUE constraint in
    the users table. The fallback to "unknown" matches `ensure_user_row`'s
    behavior when `user.provider` is empty.
    """
    return f"{user.provider or 'unknown'}:{user.user_id}"


async def _ensure_db_user(user: User, jwt_roles: list[str] | None = None) -> str | None:
    """Best-effort DB upsert for the authenticated user. Returns the SQL
    `users.id` for this user (so callers can cache the OAuth-sub → DB-id
    mapping). Returns None on failure.

    When ``jwt_roles`` is not None, the user's DB role assignments are
    reconciled against it on every call — the per-process cache short-
    circuits the user-row INSERT but not the role sync. Pass None to
    preserve pre-JWT-roles behavior.

    No-ops for anonymous users in no-auth mode beyond the very first call
    (which does set up the synthetic anonymous row + role). Failures are
    logged but never block the request.
    """
    if not user or not user.user_id:
        return None
    cache_key = _user_cache_key(user)
    cached_db_id = _ENSURED_USER_IDS.get(cache_key)
    if cached_db_id is not None and jwt_roles is None:
        return cached_db_id

    # Serialize concurrent first-time ensures for the SAME identity so a
    # second caller observes the first's committed row instead of
    # racing through the cache miss → INSERT path. Per-(provider,
    # subject) lock so unrelated users never block each other.
    lock = _ENSURE_LOCKS.setdefault(cache_key, asyncio.Lock())
    async with lock:
        cached_db_id = _ENSURED_USER_IDS.get(cache_key)
        if cached_db_id is not None and jwt_roles is None:
            return cached_db_id
        try:
            from db.engine import SessionLocal, init_engine
            from services.user_service import ensure_user_row, sync_jwt_roles

            if SessionLocal is None:
                init_engine()
            from db.engine import SessionLocal as _SessionLocal

            if _SessionLocal is None:
                return None
            async with _SessionLocal() as session:
                if cached_db_id is not None and jwt_roles is not None:
                    # User row already exists in this process; just reconcile
                    # roles from the JWT.
                    await sync_jwt_roles(session, cached_db_id, jwt_roles)
                    await session.commit()
                    return cached_db_id
                db_row = await ensure_user_row(session, user, jwt_roles=jwt_roles)
                await session.commit()
            _ENSURED_USER_IDS[cache_key] = db_row.id
            return db_row.id
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("ensure_user_row failed", user_id=user.user_id, error=str(exc))
            return None


async def _resolve_db_user_id(user: User, jwt_roles: list[str] | None = None) -> str:
    """Translate an authenticated `User` to the SQL ``users.id`` used by RBAC."""
    if not user or not user.user_id:
        return ""
    if jwt_roles is None:
        cached = _ENSURED_USER_IDS.get(_user_cache_key(user))
        if cached is not None:
            return cached
    resolved = await _ensure_db_user(user, jwt_roles=jwt_roles)
    return resolved or user.user_id


def invalidate_user_ensured_cache(
    oauth_provider: str | None = None,
    oauth_subject: str | None = None,
) -> None:
    """Pop the ensure-cache + lock for a single identity, or clear all."""
    if oauth_provider is None or oauth_subject is None:
        _ENSURED_USER_IDS.clear()
        _ENSURE_LOCKS.clear()
        return
    key = f"{oauth_provider or 'unknown'}:{oauth_subject}"
    _ENSURED_USER_IDS.pop(key, None)
    _ENSURE_LOCKS.pop(key, None)
