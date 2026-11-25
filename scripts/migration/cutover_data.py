"""Promote a verified default-SQLite restore while keeping the old directories."""

import argparse
import filecmp
import os
import sqlite3
import stat
import subprocess
import sys
from contextlib import closing
from itertools import zip_longest
from pathlib import Path
from tempfile import mkdtemp


class CutoverError(Exception):
    pass


def _directory(path: Path) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise CutoverError("Cutover requires absolute paths to existing non-symlink directories.")
    return path.resolve()


def _overlap(first: Path, second: Path) -> bool:
    return any(first.samefile(path) for path in (second, *second.parents)) or any(
        second.samefile(path) for path in first.parents
    )


def _inventory(root: Path) -> dict[Path, os.stat_result]:
    entries = {Path("."): root.stat()}

    def raise_error(error: OSError) -> None:
        raise error

    for directory, dirs, files in os.walk(root, onerror=raise_error):
        for name in dirs + files:
            path = Path(directory, name)
            info = path.lstat()
            if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise CutoverError("Cutover directories cannot contain symlinks or special files.")
            if info.st_dev != entries[Path(".")].st_dev or path.is_mount():
                raise CutoverError("Cutover directories cannot contain nested mounts.")
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise CutoverError("Cutover directories cannot contain hardlinked files.")
            entries[path.relative_to(root)] = info
    return entries


def _same_database(backup: Path, live: Path) -> bool:
    with (
        closing(sqlite3.connect(backup.as_uri() + "?mode=ro&immutable=1", uri=True)) as old,
        closing(sqlite3.connect(live.as_uri() + "?mode=ro&immutable=1", uri=True)) as current,
    ):
        for pragma in ("PRAGMA user_version", "PRAGMA application_id"):
            if old.execute(pragma).fetchone() != current.execute(pragma).fetchone():
                return False
        return all(a == b for a, b in zip_longest(old.iterdump(), current.iterdump()))


def _prepare(backup: Path, restore: Path, target: Path, *, data: bool) -> None:
    backed_up, rotated, current = (_inventory(path) for path in (backup, restore, target))
    db = Path("openrag.db") if data else None
    if db is not None:
        if db not in backed_up or db not in rotated or db not in current:
            raise CutoverError(
                "Cutover requires openrag.db in the backup, restore, and destination."
            )
        for suffix in ("-wal", "-shm", "-journal"):
            if any(
                Path(f"openrag.db{suffix}") in entries for entries in (backed_up, rotated, current)
            ):
                raise CutoverError("SQLite sidecars found; stop writers and take a fresh backup.")
    if backed_up.keys() != current.keys() or rotated.keys() != current.keys():
        raise CutoverError("Cutover file inventory changed since backup; take a fresh backup.")
    for relative, live_stat in current.items():
        kind = stat.S_IFMT(live_stat.st_mode)
        if any(stat.S_IFMT(entries[relative].st_mode) != kind for entries in (backed_up, rotated)):
            raise CutoverError("Cutover file types changed since backup; take a fresh backup.")
        if stat.S_ISDIR(live_stat.st_mode):
            continue
        if relative == db:
            unchanged = _same_database(backup / relative, target / relative)
        else:
            unchanged = filecmp.cmp(backup / relative, target / relative, shallow=False)
        if not unchanged:
            raise CutoverError("Cutover destination changed since backup; take a fresh backup.")
    # Rotation preserves the restore's metadata, but the backup wrapper can give
    # restored files a different owner or mode. Match the live runtime paths.
    for relative in sorted(current, key=lambda path: len(path.parts), reverse=True):
        live_stat, copy_stat = current[relative], rotated[relative]
        path = restore / relative
        if (live_stat.st_uid, live_stat.st_gid) != (copy_stat.st_uid, copy_stat.st_gid):
            os.chown(path, live_stat.st_uid, live_stat.st_gid)
        os.chmod(path, stat.S_IMODE(live_stat.st_mode))


def _swap(pairs: list[tuple[Path, Path]]) -> None:
    moves: list[tuple[Path, Path, Path]] = []
    try:
        for restore, target in pairs:
            rollback = Path(mkdtemp(prefix=f".{target.name}.openrag-rollback-", dir=target.parent))
            saved = rollback / target.name
            print(f"[STEP] Keeping original at {str(saved)!r}.", file=sys.stderr, flush=True)
            moves.append((restore, target, saved))
            target.rename(saved)
            restore.rename(target)
    except (OSError, KeyboardInterrupt):
        for restore, target, saved in reversed(moves):
            try:
                if saved.exists():
                    if not restore.exists():
                        target.rename(restore)
                    saved.rename(target)
            except OSError:
                raise CutoverError(
                    "Automatic rollback failed. Keep OpenRAG stopped and recover using the "
                    "printed rollback paths and the untouched backup."
                ) from None
        raise CutoverError("Cutover failed; completed moves were rolled back.") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("migration_dir", type=Path)
    parser.add_argument("data_dir", type=Path)
    parser.add_argument("config_dir", type=Path)
    args = parser.parse_args()
    try:
        if not sys.stdin.isatty():
            raise CutoverError("Cutover requires an interactive terminal.")
        migration = _directory(args.migration_dir)
        targets = [_directory(args.data_dir), _directory(args.config_dir)]
        for first, second in (
            (targets[0], targets[1]),
            *((target, migration) for target in targets),
        ):
            if _overlap(first, second):
                raise CutoverError(
                    "Migration, destination data, and destination config must not overlap."
                )
        pairs = []
        for name, target in zip(("data", "config"), targets, strict=True):
            restore = _directory(_directory(migration / "restore") / name)
            backup = _directory(_directory(migration / "backup") / name)
            if not restore.is_relative_to(migration / "restore") or not backup.is_relative_to(
                migration / "backup"
            ):
                raise CutoverError("Backup and restore must be inside the migration directory.")
            if (
                target.is_mount()
                or restore.is_mount()
                or not (
                    target.stat().st_dev == target.parent.stat().st_dev == restore.stat().st_dev
                )
            ):
                raise CutoverError(
                    "Cutover requires renameable directories on the same filesystem."
                )
            pairs.append((restore, target))
        print("[STEP] Verifying the restore with the replacement key.", file=sys.stderr)
        data, config = (restore for restore, _ in pairs)
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("rotate_encryption_key.py")),
                "verify",
                "--data-dir",
                str(data),
                "--config-dir",
                str(config),
                "--sqlite",
                str(data / "openrag.db"),
                "--source-data-dir",
                os.environ.get("OLD_DATA_PATH_AS_STORED") or "data",
                "--tenant-id",
                os.environ.get("OPENRAG_TENANT_ID") or "openrag",
                "--new-key-file",
                str(migration / "keys/new"),
            ],
            check=False,
        )
        if result.returncode != 0:
            raise CutoverError("Replacement-key verification failed.")
        print(
            f"[WARNING] Replace {str(targets[0])!r} and {str(targets[1])!r}. "
            "Keep all OpenRAG writers stopped. This does not change the key.",
            file=sys.stderr,
        )
        print("Type cutover-data to confirm: ", end="", file=sys.stderr, flush=True)
        if input() != "cutover-data":
            raise CutoverError("Cutover cancelled.")
        for (restore, target), name in zip(pairs, ("data", "config"), strict=True):
            backup = migration / "backup" / name
            print(
                f"[STEP] Checking destination {str(target)!r} against its backup.",
                file=sys.stderr,
            )
            _prepare(backup, restore, target, data=name == "data")
        _swap(pairs)
    except (CutoverError, OSError, sqlite3.Error, EOFError, KeyboardInterrupt) as error:
        detail = str(error) if isinstance(error, CutoverError) else type(error).__name__
        print(f"[ERROR] {detail} Cutover not completed. Keep OpenRAG stopped.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
