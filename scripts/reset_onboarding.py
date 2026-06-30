#!/usr/bin/env python3
"""Reset onboarding state in the DB so the wizard shows again.

Sets ``meta.edited=false`` and clears the ``onboarding`` section in
``workspace_config``. In hybrid/files mode, config.yaml is updated too.

Does **not** remove ingested documents, knowledge filters, or Langflow
flow edits. For that, use POST /settings/rollback-onboarding via the API.

Usage:
    uv run python scripts/reset_onboarding.py
    uv run python scripts/reset_onboarding.py --dry-run
    uv run python scripts/reset_onboarding.py --reset-models
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
        description="Reset onboarding in workspace_config to re-trigger the wizard.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing",
    )
    parser.add_argument(
        "--reset-models",
        action="store_true",
        help="Also clear selected LLM and embedding models (back to openai defaults)",
    )
    args = parser.parse_args()

    from config.storage_mode import db_writes_enabled, get_storage_mode
    from services.onboarding_reset import reset_onboarding

    mode = get_storage_mode()
    print(f"Storage mode: {mode}")

    session = None
    if db_writes_enabled():
        import db.engine as db_engine

        db_engine.init_engine()
        SessionLocal = db_engine.SessionLocal
        if SessionLocal is None:
            print("Database engine is not configured (check DATABASE_URL).", file=sys.stderr)
            return 1

        async with SessionLocal() as session:
            result = await reset_onboarding(
                session,
                reset_models=args.reset_models,
                dry_run=args.dry_run,
            )
            if not args.dry_run:
                await session.commit()
    else:
        result = await reset_onboarding(
            None,
            reset_models=args.reset_models,
            dry_run=args.dry_run,
        )

    if args.dry_run:
        print(
            f"Dry run — would set edited=false and onboarding.current_step=0 "
            f"(was edited={result.previous_edited!r}, step={result.previous_step!r})."
        )
        if args.reset_models:
            print("Would also clear LLM and embedding model selections.")
    else:
        targets = []
        if result.db_updated:
            targets.append("workspace_config (DB)")
        if result.yaml_updated:
            targets.append("config.yaml")
        print(f"Onboarding reset written to: {', '.join(targets) or 'nothing'}")
        print("Restart the backend, then reload the app to see the onboarding wizard.")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
