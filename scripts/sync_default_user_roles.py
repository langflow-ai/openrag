#!/usr/bin/env python3
"""Sync existing user roles when OPENRAG_DEFAULT_ROLE env values change.

Requires ``OPENRAG_SYNC_DEFAULT_ROLE=true`` (same flag used at backend
startup). Only users whose sole role matches the previously recorded env
default are updated.

Usage:
    OPENRAG_SYNC_DEFAULT_ROLE=true uv run python scripts/sync_default_user_roles.py
    OPENRAG_SYNC_DEFAULT_ROLE=true uv run python scripts/sync_default_user_roles.py --dry-run
    OPENRAG_SYNC_DEFAULT_ROLE=true uv run python scripts/sync_default_user_roles.py --record-baseline
    OPENRAG_SYNC_DEFAULT_ROLE=true uv run python scripts/sync_default_user_roles.py --from-role user
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync DB user roles after OPENRAG_DEFAULT_ROLE / OPENRAG_NOAUTH_ROLE change.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show eligible updates without writing to the DB",
    )
    parser.add_argument(
        "--record-baseline",
        action="store_true",
        help="Record current env defaults without updating any users",
    )
    parser.add_argument(
        "--from-role",
        metavar="ROLE",
        help=(
            "Treat ROLE as the previous default for this run only "
            "(fixes a baseline recorded before users were migrated)"
        ),
    )
    parser.add_argument(
        "--from-noauth-role",
        metavar="ROLE",
        help="Like --from-role but for the anonymous/no-auth user",
    )
    args = parser.parse_args()

    import db.engine as db_engine
    from config.settings import (
        get_default_user_role,
        get_noauth_user_role,
        is_default_role_sync_enabled,
    )
    from services.default_role_sync import sync_default_roles_if_changed

    if not is_default_role_sync_enabled():
        from utils.run_mode_utils import get_run_mode, is_run_mode_oss

        if not is_run_mode_oss():
            print(
                "Default role sync is only available when OPENRAG_RUN_MODE=oss "
                f"(current: {get_run_mode()!r}).",
                file=sys.stderr,
            )
        else:
            print(
                "OPENRAG_SYNC_DEFAULT_ROLE is not enabled. "
                "Set OPENRAG_SYNC_DEFAULT_ROLE=true and retry.",
                file=sys.stderr,
            )
        return 1

    db_engine.init_engine()
    SessionLocal = db_engine.SessionLocal
    if SessionLocal is None:
        print("Database engine is not configured (check DATABASE_URL).", file=sys.stderr)
        return 1

    print(
        f"Target defaults: OPENRAG_DEFAULT_ROLE={get_default_user_role()!r}, "
        f"OPENRAG_NOAUTH_ROLE={get_noauth_user_role()!r}"
    )
    if args.dry_run:
        print("Dry run — no writes.")

    async with SessionLocal() as session:
        result = await sync_default_roles_if_changed(
            session,
            dry_run=args.dry_run,
            force_baseline=args.record_baseline,
            from_role=args.from_role,
            from_noauth_role=args.from_noauth_role,
        )
        if not args.dry_run:
            await session.commit()

    if result.baseline_recorded and not result.changes and args.record_baseline:
        print("Baseline recorded; no user rows changed.")
    elif result.updated_users == 0:
        print("No eligible users to update.")
        if result.stale_users:
            print(
                f"Found {result.stale_users} user(s) whose sole role differs from "
                f"OPENRAG_DEFAULT_ROLE={get_default_user_role()!r} but the stored "
                "baseline already matches env. Re-run with:\n"
                f"  --from-role user   # or whichever role they currently have"
            )
    else:
        verb = "Would update" if args.dry_run else "Updated"
        print(f"{verb} {result.updated_users} user(s):")
        for change in result.changes:
            print(
                f"  - {change['user_id']} ({change['oauth_provider']}:{change['oauth_subject']}): "
                f"{change['from_role']} -> {change['to_role']}"
            )
    if result.skipped_users:
        print(f"Skipped {result.skipped_users} user(s) (multi-role or non-default role).")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
