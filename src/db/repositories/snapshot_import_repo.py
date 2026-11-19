"""Async data access for snapshot sources, imports and datasets.

Callers own the transaction (``session.commit()``); every method only flushes.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import SnapshotDataset, SnapshotImport, SnapshotSource

JOB_STARTABLE_STATES = ("idle", "failed", "cancelled")
JOB_ACTIVE_STATES = ("queued", "running")
JOB_RECOVERY_STATE = "recovery"


def _now() -> datetime:
    return datetime.now(UTC)


class SnapshotImportRepo:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ── sources ──────────────────────────────────────────────────────────
    async def add_source(self, source: SnapshotSource) -> SnapshotSource:
        self.session.add(source)
        await self.session.flush()
        return source

    async def get_source(self, source_id: str) -> SnapshotSource | None:
        return await self.session.get(SnapshotSource, source_id)

    async def list_sources(self, owner_user_id: str) -> list[SnapshotSource]:
        result = await self.session.execute(
            select(SnapshotSource)
            .where(SnapshotSource.owner_user_id == owner_user_id)
            .order_by(SnapshotSource.created_at, SnapshotSource.id)
        )
        return list(result.scalars())

    async def delete_source(self, source: SnapshotSource) -> None:
        await self.session.delete(source)
        await self.session.flush()

    async def count_imports_for_source(self, source_id: str) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(SnapshotImport)
            .where(SnapshotImport.source_id == source_id)
        )
        return int(result.scalar_one())

    # ── imports ──────────────────────────────────────────────────────────
    async def add_import(
        self, row: SnapshotImport, datasets: Iterable[SnapshotDataset] = ()
    ) -> SnapshotImport:
        self.session.add(row)
        await self.session.flush()
        for dataset in datasets:
            self.session.add(dataset)
        await self.session.flush()
        return row

    async def get_import(self, import_id: str) -> SnapshotImport | None:
        return await self.session.get(SnapshotImport, import_id)

    async def get_import_by_slug(self, slug: str) -> SnapshotImport | None:
        result = await self.session.execute(
            select(SnapshotImport).where(SnapshotImport.slug == slug)
        )
        return result.scalar_one_or_none()

    async def list_visible_imports(self, user_id: str) -> list[SnapshotImport]:
        result = await self.session.execute(
            select(SnapshotImport)
            .where((SnapshotImport.owner_user_id == user_id) | (SnapshotImport.shared.is_(True)))
            .order_by(SnapshotImport.created_at, SnapshotImport.id)
        )
        return list(result.scalars())

    async def list_imports_in_job_states(self, states: Iterable[str]) -> list[SnapshotImport]:
        result = await self.session.execute(
            select(SnapshotImport).where(SnapshotImport.job_state.in_(tuple(states)))
        )
        return list(result.scalars())

    async def list_all_imports(self) -> list[SnapshotImport]:
        result = await self.session.execute(
            select(SnapshotImport).order_by(SnapshotImport.created_at)
        )
        return list(result.scalars())

    async def count_user_imports(self, owner_user_id: str) -> int:
        """Imports that are not being deleted (they count against the per-user cap)."""
        result = await self.session.execute(
            select(func.count())
            .select_from(SnapshotImport)
            .where(
                SnapshotImport.owner_user_id == owner_user_id, SnapshotImport.status != "deleting"
            )
        )
        return int(result.scalar_one())

    async def known_snapshot_uuids(self, owner_user_id: str, source_id: str) -> set[str]:
        result = await self.session.execute(
            select(SnapshotImport.snapshot_uuid).where(
                SnapshotImport.owner_user_id == owner_user_id,
                SnapshotImport.source_id == source_id,
                SnapshotImport.status != "deleting",
            )
        )
        return {uuid for uuid in result.scalars() if uuid}

    async def reserve_job(
        self,
        import_id: str,
        kind: str,
        *,
        allow_from: Iterable[str] = JOB_STARTABLE_STATES,
        **values: Any,
    ) -> bool:
        """Atomically move ``job_state`` from an allowed state to ``queued``.

        Returns False when another job holds the import. ``values`` are applied
        in the same UPDATE (status, job_error, task_id, ...).
        """
        result = await self.session.execute(
            update(SnapshotImport)
            .where(SnapshotImport.id == import_id, SnapshotImport.job_state.in_(tuple(allow_from)))
            .values(job_state="queued", job_kind=kind, job_error=None, updated_at=_now(), **values)
        )
        return bool(result.rowcount)

    async def update_import(self, import_id: str, **values: Any) -> None:
        await self.session.execute(
            update(SnapshotImport)
            .where(SnapshotImport.id == import_id)
            .values(updated_at=_now(), **values)
        )

    async def delete_import(self, import_id: str) -> None:
        await self.session.execute(
            delete(SnapshotDataset).where(SnapshotDataset.import_id == import_id)
        )
        await self.session.execute(delete(SnapshotImport).where(SnapshotImport.id == import_id))
        await self.session.flush()

    # ── datasets ─────────────────────────────────────────────────────────
    async def list_datasets(self, import_id: str) -> list[SnapshotDataset]:
        result = await self.session.execute(
            select(SnapshotDataset)
            .where(SnapshotDataset.import_id == import_id)
            .order_by(SnapshotDataset.ordinal)
        )
        return list(result.scalars())

    async def get_dataset(self, import_id: str, dataset_id: str) -> SnapshotDataset | None:
        result = await self.session.execute(
            select(SnapshotDataset).where(
                SnapshotDataset.import_id == import_id, SnapshotDataset.id == dataset_id
            )
        )
        return result.scalar_one_or_none()

    async def add_datasets(self, datasets: Iterable[SnapshotDataset]) -> None:
        for dataset in datasets:
            self.session.add(dataset)
        await self.session.flush()

    async def update_dataset(self, dataset_id: str, **values: Any) -> None:
        await self.session.execute(
            update(SnapshotDataset)
            .where(SnapshotDataset.id == dataset_id)
            .values(updated_at=_now(), **values)
        )

    async def list_active_datasets_for_user(
        self, user_id: str
    ) -> list[tuple[SnapshotImport, SnapshotDataset]]:
        """Datasets of active imports the user owns or that are shared."""
        result = await self.session.execute(
            select(SnapshotImport, SnapshotDataset)
            .join(SnapshotDataset, SnapshotDataset.import_id == SnapshotImport.id)
            .where(
                SnapshotImport.status == "active",
                (SnapshotImport.owner_user_id == user_id) | (SnapshotImport.shared.is_(True)),
            )
            .order_by(SnapshotImport.created_at, SnapshotDataset.ordinal)
        )
        return [(imp, ds) for imp, ds in result.all()]
