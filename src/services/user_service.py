"""User lifecycle service.

Single chokepoint for "given an authenticated principal, make sure a row
exists in the users table and assign a default role." Race-safe via a
serialized SQL transaction. Idempotent.

ensure_user_row is intentionally synchronous on its critical section so
parallel sign-ins from the same provider/subject collapse into a single
INSERT (the unique constraint on (oauth_provider, oauth_subject) does the
heavy lifting; we catch IntegrityError and re-fetch).
"""

from __future__ import annotations

import os
import uuid
from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User as UserRow
from db.repositories import AuditRepo, RoleRepo, UserRepo
from session_manager import User
from utils.logging_config import get_logger

logger = get_logger(__name__)


def _default_new_user_role() -> str:
    return os.getenv("OPENRAG_DEFAULT_ROLE", "user")


def _noauth_role() -> str:
    return os.getenv("OPENRAG_NOAUTH_ROLE", "admin")


async def ensure_user_row(session: AsyncSession, user: User) -> UserRow:
    """Ensure the authenticated `user` exists in the SQL `users` table.

    First-ever user gets the `admin` role. All subsequent users get the
    role named in `OPENRAG_DEFAULT_ROLE` (default `user`). The synthetic
    no-auth user is granted `OPENRAG_NOAUTH_ROLE` (default `admin`).

    Returns the persisted UserRow. Caller commits.
    """

    if not user or not user.user_id:
        raise ValueError("ensure_user_row requires a user with a user_id")

    user_repo = UserRepo(session)
    role_repo = RoleRepo(session)
    audit_repo = AuditRepo(session)

    provider = user.provider or "unknown"
    subject = user.user_id

    existing = await user_repo.get_by_oauth(provider, subject)
    if existing:
        await user_repo.update_last_login(existing.id)
        return existing

    # Possible legacy row (oauth_provider='legacy', oauth_subject==user_id)
    legacy = await user_repo.get_by_oauth("legacy", subject)
    if legacy is None and user.email:
        # Or a legacy row matched by email_lookup_hash from a prior sign-in
        by_email = await user_repo.get_by_email(user.email)
        if by_email and by_email.oauth_provider == "legacy":
            legacy = by_email

    if legacy is not None:
        merged = await user_repo.merge_legacy(
            legacy,
            real_provider=provider,
            real_subject=subject,
            email=user.email,
            display_name=user.name,
            picture_url=user.picture,
        )
        await audit_repo.write(
            event="user.merged_legacy",
            actor_user_id=merged.id,
            target_type="user",
            target_id=merged.id,
            audit_metadata={"provider": provider},
        )
        # Legacy rows had no role assignment — give them the default.
        await _assign_bootstrap_or_default(session, role_repo, audit_repo, merged.id)
        return merged

    # Brand-new row.
    # We use the OAuth subject (== user.user_id) as the DB primary key so
    # the SQL `users.id` lines up with the JWT subject and with the
    # user_id strings already used by connections.json / conversations.json.
    # If a different provider ever sign-ins with the same subject string we
    # fall back to a UUID — extremely rare in practice.
    new_id = subject if subject else str(uuid.uuid4())
    row = UserRow(
        id=new_id,
        oauth_provider=provider,
        oauth_subject=subject,
        email=user.email,
        display_name=user.name,
        picture_url=user.picture,
    )
    try:
        await user_repo.add(row)
    except IntegrityError:
        # The collision could be on any of the three unique constraints:
        # (oauth_provider, oauth_subject), email_lookup_hash, or id (PK).
        # Only the FIRST means we hit our own identity (same logical
        # user via concurrent insert by a peer process); the latter two
        # mean a *different* identity already owns that id or email.
        await session.rollback()
        existing = await user_repo.get_by_oauth(provider, subject)
        if existing:
            await user_repo.update_last_login(existing.id)
            return existing
        # PK collision across providers (different subject chose the
        # same id). Retry with a UUID id; (provider, subject) and email
        # differ from the conflicting row so this insert succeeds.
        # email_lookup_hash collision is NOT recoverable here — that's
        # a real conflict (two identities with the same email) and we
        # let it propagate to the caller.
        new_id = str(uuid.uuid4())
        row = UserRow(
            id=new_id,
            oauth_provider=provider,
            oauth_subject=subject,
            email=user.email,
            display_name=user.name,
            picture_url=user.picture,
        )
        await user_repo.add(row)

    await _assign_bootstrap_or_default(session, role_repo, audit_repo, row.id)
    return row


async def _assign_bootstrap_or_default(
    session: AsyncSession,
    role_repo: RoleRepo,
    audit_repo: AuditRepo,
    user_id: str,
) -> None:
    admin_count = await role_repo.count_admins()
    if admin_count == 0:
        admin_role = await role_repo.get_by_name("admin")
        if admin_role is None:
            logger.warning("admin role not seeded; skipping bootstrap assignment")
            return
        await role_repo.assign_role(user_id, admin_role.id)
        await session.flush()

        # Race-detect: a concurrent caller may have *also* observed
        # admin_count == 0 and granted admin to a different user. Both
        # writes succeeded (no DB-level mutex). Resolve by lexicographic
        # tie-break — only the smallest user_id keeps admin; others
        # demote and fall through to the default-role path. This is
        # portable across SQLite and Postgres without advisory locks.
        admins = await role_repo.list_admin_user_ids()
        if len(admins) > 1 and min(admins) != user_id:
            await role_repo.revoke_role(user_id, admin_role.id)
            await session.flush()
            logger.warning(
                "bootstrap race detected; demoted to default role",
                user_id=user_id,
                winner=min(admins),
            )
            # Fall through to the default-role assignment block below.
        else:
            await audit_repo.write(
                event="user.bootstrap_admin",
                actor_user_id=user_id,
                target_type="user",
                target_id=user_id,
            )
            return

    # No-auth synthetic user -> configurable role
    if user_id == "anonymous":
        target_name = _noauth_role()
    else:
        target_name = _default_new_user_role()

    role = await role_repo.get_by_name(target_name)
    if role is None:
        logger.warning(
            "default role not found, skipping role assignment",
            role_name=target_name,
            user_id=user_id,
        )
        return
    await role_repo.assign_role(user_id, role.id)
    await audit_repo.write(
        event="user.created",
        actor_user_id=user_id,
        target_type="user",
        target_id=user_id,
        audit_metadata={"role": target_name},
    )


async def get_effective_provider_keys(session: AsyncSession, user_id: str) -> dict:
    """Phase-4 helper. Returns a dict of provider -> overrides for this user.

    Phase 1 ships a no-op shape so call sites can be wired without behavior
    change. Phase 4 will fill it in by reading user_preferences.provider_overrides
    and overlaying onto config_manager's workspace defaults.
    """
    return {}


async def get_effective_agent_config(session: AsyncSession, user_id: str) -> Optional[dict]:
    """Phase-4 helper. Returns the per-user agent config overlay (or None)."""
    return None
