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


async def ensure_user_row(
    session: AsyncSession,
    user: User,
    jwt_roles: list[str] | None = None,
) -> UserRow:
    """Ensure the authenticated `user` exists in the SQL `users` table.

    Role assignment:

    * ``jwt_roles is None`` — env-default behavior (oss / RBAC-off). Every new
      user gets ``OPENRAG_DEFAULT_ROLE`` (default ``user``); the synthetic
      anonymous user gets ``OPENRAG_NOAUTH_ROLE`` (default ``admin``). There is
      no first-user-becomes-admin bootstrap.
    * ``jwt_roles is not None`` — JWT is authoritative (saas / on_prem). The
      user's DB role assignments are reconciled against the list every call.

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
        if jwt_roles is not None:
            await _sync_jwt_roles(role_repo, audit_repo, existing.id, jwt_roles)
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
        if jwt_roles is not None:
            await _sync_jwt_roles(role_repo, audit_repo, merged.id, jwt_roles)
        else:
            # Legacy rows had no role assignment — give them the default.
            await _assign_default_role(session, role_repo, audit_repo, merged.id)
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
        # By the time the flush raises, the peer transaction that lost the
        # race has committed, so the re-fetches below see its row.
        await session.rollback()

        # Case 1: (oauth_provider, oauth_subject) race — a peer beat us to the
        # INSERT for this exact identity.
        existing = await user_repo.get_by_oauth(provider, subject)
        if existing:
            await user_repo.update_last_login(existing.id)
            return existing

        # Case 2: email_lookup_hash collision — some row already owns this
        # email (email_lookup_hash is UNIQUE). Most common for the synthetic
        # anonymous@localhost user in no-auth mode when two concurrent requests
        # both observe an empty table.
        by_email = await user_repo.get_by_email(user.email) if user.email else None
        if by_email is not None:
            if by_email.oauth_provider == provider and by_email.oauth_subject == subject:
                # Concurrent insert of the *same* identity — safe to reuse.
                await user_repo.update_last_login(by_email.id)
                return by_email

            # A *different* identity already owns this email (e.g. the same
            # person signing in through a second provider). Re-inserting with
            # the same email is futile — it would collide on email_lookup_hash
            # again — so create this distinct principal *without* the email so
            # the request never fails on a UNIQUE constraint. The email stays
            # attached to the first identity that claimed it.
            logger.warning(
                "email already owned by another identity; creating user row without email",
                provider=provider,
                subject=subject,
                existing_provider=by_email.oauth_provider,
                existing_subject=by_email.oauth_subject,
            )
            row = UserRow(
                id=str(uuid.uuid4()),
                oauth_provider=provider,
                oauth_subject=subject,
                email=None,
                display_name=user.name,
                picture_url=user.picture,
            )
            await user_repo.add(row)
            if jwt_roles is not None:
                await _sync_jwt_roles(role_repo, audit_repo, row.id, jwt_roles)
            else:
                await _assign_default_role(session, role_repo, audit_repo, row.id)
            return row

        # Case 3: pure PK collision (id==subject already occupied by a
        # different identity, no email conflict). Retry with a UUID;
        # (provider, subject) differs from the conflicting row so the INSERT
        # succeeds.
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

    if jwt_roles is not None:
        await _sync_jwt_roles(role_repo, audit_repo, row.id, jwt_roles)
    else:
        await _assign_default_role(session, role_repo, audit_repo, row.id)
    return row


async def sync_jwt_roles(session: AsyncSession, user_id: str, jwt_roles: list[str]) -> None:
    """Public entry point for re-syncing a user's roles from JWT claims.

    Used by the ensure-user cache fast path in ``dependencies.py``: when the
    user row is already in the per-process cache we skip ``ensure_user_row``
    but still need to reconcile roles each request. Caller commits.
    """
    role_repo = RoleRepo(session)
    audit_repo = AuditRepo(session)
    await _sync_jwt_roles(role_repo, audit_repo, user_id, jwt_roles)


async def _sync_jwt_roles(
    role_repo: RoleRepo,
    audit_repo: AuditRepo,
    user_id: str,
    jwt_roles: list[str],
) -> None:
    """Reconcile ``user_roles`` for ``user_id`` against the JWT-derived list.

    JWT is authoritative: roles missing from the JWT are revoked, new ones
    are added. Role names not present in the ``roles`` table are skipped
    (logged at WARNING). A single ``user.roles_synced`` audit row is written
    when the role set changes.
    """
    current = await role_repo.list_user_roles(user_id)
    current_by_name = {r.name: r for r in current}

    desired: dict[str, str] = {}  # name -> role_id
    for name in jwt_roles:
        if name in desired:
            continue
        role = await role_repo.get_by_name(name)
        if role is None:
            logger.warning(
                "JWT role not present in roles table; skipping",
                role=name,
                user_id=user_id,
            )
            continue
        desired[name] = role.id

    added: list[str] = []
    removed: list[str] = []

    for name, role_id in desired.items():
        if name not in current_by_name:
            await role_repo.assign_role(user_id, role_id)
            added.append(name)

    for name, role in current_by_name.items():
        if name not in desired:
            await role_repo.revoke_role(user_id, role.id)
            removed.append(name)

    if added or removed:
        await audit_repo.write(
            event="user.roles_synced",
            actor_user_id=user_id,
            target_type="user",
            target_id=user_id,
            audit_metadata={"added": added, "removed": removed, "source": "jwt"},
        )


async def _assign_default_role(
    session: AsyncSession,
    role_repo: RoleRepo,
    audit_repo: AuditRepo,
    user_id: str,
) -> None:
    """Assign the configured default role to a freshly-created user.

    Role assignment is owned outside the app: saas/on_prem deployments sync
    roles from the JWT claim (see ``_sync_jwt_roles``), and everything else
    falls back here. There is no first-user-becomes-admin bootstrap — an oss
    operator who wants an admin sets ``OPENRAG_DEFAULT_ROLE=admin``.
    """
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


async def get_effective_agent_config(session: AsyncSession, user_id: str) -> dict | None:
    """Phase-4 helper. Returns the per-user agent config overlay (or None)."""
    return None
