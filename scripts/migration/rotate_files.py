"""Rotate only openrag.db and connections.json in a stopped SQLite deployment."""

import argparse
import asyncio
import hashlib
import json
import os
import shutil
import stat
import sys
from argparse import Namespace
from pathlib import Path
from tempfile import TemporaryDirectory

from cutover_data import CutoverError, _reject_acl
from rotate_encryption_key import (
    _CACHE_NAME,
    _LEGACY_FILES,
    RotationError,
    _file,
    _key,
    _Parser,
    _Rotation,
    _run,
)


def _hash(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _copy(source: Path, destination: Path, mode_from: Path | None = None) -> None:
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output, source.open("rb") as stream:
        shutil.copyfileobj(stream, output)
        output.flush()
        if mode_from is not None:
            original, copy = mode_from.stat(), os.fstat(output.fileno())
            if (copy.st_uid, copy.st_gid) != (original.st_uid, original.st_gid):
                os.fchown(output.fileno(), original.st_uid, original.st_gid)
            os.fchmod(output.fileno(), stat.S_IMODE(original.st_mode))
        os.fsync(output.fileno())


def _inspect(args: argparse.Namespace, data: Path, config: Path, rotation: _Rotation) -> None:
    mode = "apply-to-copy" if rotation.write_key is not None else "check"
    options = Namespace(
        mode=mode,
        data_dir=data,
        config_dir=config,
        sqlite=data / "openrag.db",
        postgres_url_file=None,
        original_data_dir=args.sqlite.parent.resolve(),
        original_config_dir=args.config_dir.resolve(),
        source_data_dir=args.source_data_dir,
        tenant_id=args.tenant_id,
        token_cache=[],
        map_token_cache=[],
    )
    asyncio.run(_run(options, rotation))
    extras = {
        "config.yaml providers",
        "legacy state files",
        "OAuth token caches",
        "absent OAuth cache paths",
    }
    if extras & rotation.counts.keys():
        raise RotationError(
            "Additional encrypted files or missing OAuth caches require a full restore migration."
        )
    if not rotation.counts:
        raise RotationError("No ciphertext found; the key could not be authenticated.")


def _publish(directory: Path, sources: list[Path], names: list[Path]) -> None:
    published = []
    with TemporaryDirectory(prefix=".openrag-file-artifacts-", dir=directory) as temp:
        staging = Path(temp)
        for source in sources:
            _copy(source, staging / source.name)
        try:
            for source, destination in zip(sources, names, strict=True):
                os.link(staging / source.name, destination)
                published.append(destination)
            _sync_directory(directory)
        except (OSError, KeyboardInterrupt):
            for destination in published:
                destination.unlink()
            raise


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _require_offline_sqlite(database: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = database.with_name(database.name + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            raise RotationError("SQLite sidecars found. Stop writers and checkpoint the database.")


def _unchanged(originals: list[Path], backups: list[Path]) -> None:
    _require_offline_sqlite(originals[0])
    if any(_hash(a) != _hash(b) for a, b in zip(originals, backups, strict=True)):
        raise RotationError("Original files changed since backup; take a fresh backup.")


def _backup(originals: list[Path], backups: list[Path]) -> None:
    parent = originals[0].parent
    if any(path.exists() or path.is_symlink() for path in backups):
        raise RotationError("Backup files already exist; nothing was overwritten.")
    _require_offline_sqlite(originals[0])
    with TemporaryDirectory(prefix=".openrag-file-backup-", dir=parent) as temp:
        staged = [Path(temp) / backup.name for backup in backups]
        for original, copy in zip(originals, staged, strict=True):
            _copy(original, copy)
        _unchanged(originals, staged)
        _publish(parent, staged, backups)


def _report(rotation: _Rotation) -> None:
    for area, count in sorted(rotation.counts.items()):
        print(f"{area}: {count}")


def _key_path(explicit: Path | None, name: str, flag: str) -> Path:
    if explicit is not None:
        return explicit
    if workspace := os.getenv("MIGRATION_DIR"):
        root = Path(workspace)
        keys = root / "keys"
        path = keys / name
        if root.is_absolute() and not any(p.is_symlink() for p in (root, keys, path)):
            if path.is_file():
                return path
    raise RotationError(f"Run files keys first or pass {flag}.")


def _cutover(
    originals: list[Path], backups: list[Path], promoted: list[Path], scratch: Path
) -> None:
    rollback = []
    for original, backup in zip(originals, backups, strict=True):
        _reject_acl(original)
        copy = scratch / (original.name + ".rollback")
        _copy(backup, copy, mode_from=original)
        rollback.append(copy)
    _unchanged(originals, backups)
    try:
        for source, target in zip(promoted, originals, strict=True):
            source.replace(target)
        _sync_directory(originals[0].parent)
    except (OSError, KeyboardInterrupt):
        try:
            for source, target, replacement in zip(rollback, originals, promoted, strict=True):
                if not replacement.exists():
                    source.replace(target)
            _sync_directory(originals[0].parent)
        except (OSError, KeyboardInterrupt):
            raise RotationError(
                "Rollback failed. Keep OpenRAG stopped and restore both .backup files."
            ) from None
        raise RotationError("Cutover failed and the original files were restored.") from None


def main() -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument("mode", choices=("backup", "dry-run", "apply", "check", "cutover"))
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--connections", type=Path, required=True)
    parser.add_argument(
        "--config-dir", type=Path, help="runtime config directory (defaults to data/config)"
    )
    parser.add_argument("--source-data-dir", type=Path)
    parser.add_argument("--tenant-id", default=os.getenv("OPENRAG_TENANT_ID") or "openrag")
    parser.add_argument("--old-key-file", type=Path)
    key = parser.add_mutually_exclusive_group()
    key.add_argument("--new-key-file", type=Path)
    key.add_argument("--key-file", type=Path, help="check only: use this key to decrypt the files")
    parser.add_argument("--migrated", action="store_true", help="check the .migrated files instead")
    args = parser.parse_args()
    try:
        if (args.migrated or args.key_file is not None) and args.mode != "check":
            raise RotationError("--migrated and --key-file are only available with check.")
        if args.sqlite.name != "openrag.db" or args.connections.name != "connections.json":
            raise RotationError("Use the original filenames openrag.db and connections.json.")
        parent = args.sqlite.parent.resolve()
        if args.connections.parent.resolve() != parent:
            raise RotationError("Both files must be in the same directory.")
        originals = [
            path
            for name in ("openrag.db", "connections.json")
            if (path := _file(parent, Path(name), required=True)) is not None
        ]
        args.source_data_dir = args.source_data_dir or parent
        args.config_dir = args.config_dir or parent / "config"
        config_files = (parent / "config.yaml", args.config_dir / "config.yaml")
        if any(path.exists() or path.is_symlink() for path in config_files):
            raise RotationError("config.yaml found; use the full restore migration.")
        if any(
            Path(path.name) in _LEGACY_FILES or _CACHE_NAME.fullmatch(path.name)
            for path in parent.iterdir()
        ):
            raise RotationError(
                "OAuth caches or legacy state files found; use the full restore migration."
            )
        backups = [path.with_name(path.name + ".backup") for path in originals]
        migrated = [path.with_name(path.name + ".migrated") for path in originals]
        receipt = parent / "openrag.db.migrated.sha256.json"
        if args.mode == "backup":
            _backup(originals, backups)
            print("[OK] Created both .backup files. Originals were not changed.")
            return 0
        if args.mode == "check":
            check_key = _key_path(args.key_file or args.new_key_file, "new", "--key-file")
            selected = migrated if args.migrated else originals
            print(
                f"[STEP] Checking {str(selected[0])!r} and {str(selected[1])!r} "
                f"with key file {str(check_key)!r}.",
                file=sys.stderr,
            )
            verification = _Rotation(_key(check_key, new=args.key_file is None), None)
            if args.migrated:
                _require_offline_sqlite(migrated[0])
                with TemporaryDirectory(prefix="openrag-file-check-") as temp:
                    stage = Path(temp)
                    for original, moved in zip(originals, migrated, strict=True):
                        _file(parent, Path(moved.name), required=True)
                        _copy(moved, stage / original.name)
                    _inspect(args, stage, stage, verification)
            else:
                _inspect(args, parent, parent, verification)
            _report(verification)
            print("[OK] The supplied key authenticated the stored ciphertext.")
            return 0
        if args.mode in ("dry-run", "apply"):
            old = _key(_key_path(args.old_key_file, "old", "--old-key-file"), new=False)
            print(
                "[STEP] Checking the original SQLite database and connections read-only.",
                file=sys.stderr,
            )
            preflight = _Rotation(old, None)
            _inspect(args, parent, parent, preflight)
            if args.mode == "dry-run":
                _report(preflight)
                return 0
            new = _key(_key_path(args.new_key_file, "new", "--new-key-file"), new=True)
            if old == new:
                raise RotationError("Old and replacement keys must differ.")
            if any(path.exists() or path.is_symlink() for path in [*migrated, receipt]):
                raise RotationError("Migrated files already exist; nothing was overwritten.")
            if not any(path.exists() or path.is_symlink() for path in backups):
                _backup(originals, backups)
            for backup in backups:
                _file(parent, Path(backup.name), required=True)
            _unchanged(originals, backups)
            with TemporaryDirectory(prefix="openrag-file-rotation-") as temp:
                stage = Path(temp)
                files = [stage / path.name for path in originals]
                for backup, replica in zip(backups, files, strict=True):
                    _copy(backup, replica)
                print(
                    "[STEP] Rotating temporary copies and verifying with the new key.",
                    file=sys.stderr,
                )
                _inspect(args, stage, stage, _Rotation(old, new))
                verification = _Rotation(new, None)
                _inspect(args, stage, stage, verification)
                if verification.counts != preflight.counts:
                    raise RotationError("Ciphertext counts changed during rotation.")
                seal = stage / receipt.name
                fd = os.open(seal, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump([_hash(path) for path in [*backups, *files]], stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                _unchanged(originals, backups)
                _publish(parent, [*files, seal], [*migrated, receipt])
            print("[OK] Created and verified .migrated files. Originals and backups are unchanged.")
            return 0
        new = _key(_key_path(args.new_key_file, "new", "--new-key-file"), new=True)
        if not sys.stdin.isatty():
            raise RotationError("Cutover requires an interactive terminal.")
        _require_offline_sqlite(migrated[0])
        for artifact in [*backups, *migrated, receipt]:
            _file(parent, Path(artifact.name), required=True)
        hashes = json.loads(receipt.read_text(encoding="utf-8"))
        if hashes != [_hash(path) for path in [*backups, *migrated]]:
            raise RotationError("Backup or migrated files changed since apply.")
        _unchanged(originals, backups)
        with TemporaryDirectory(prefix=".openrag-file-cutover-", dir=parent) as temp:
            stage = Path(temp)
            promoted = [stage / path.name for path in originals]
            for migrated_file, replica, original in zip(migrated, promoted, originals, strict=True):
                _copy(migrated_file, replica, mode_from=original)
            if hashes[2:] != [_hash(path) for path in promoted]:
                raise RotationError("Migrated files changed during cutover.")
            _inspect(args, stage, stage, _Rotation(new, None))
            print(
                f"[WARNING] Replace {str(originals[0])!r} and {str(originals[1])!r}. "
                "Keep writers stopped. This does not change the key.",
                file=sys.stderr,
            )
            print("Type cutover-files to confirm: ", end="", file=sys.stderr, flush=True)
            if input() != "cutover-files":
                raise RotationError("Cutover cancelled.")
            _cutover(originals, backups, promoted, stage)
        print(
            "[OK] Data cutover complete. Configure the replacement key before restarting OpenRAG."
        )
        return 0
    except (Exception, KeyboardInterrupt) as error:
        detail = (
            str(error) if isinstance(error, (RotationError, CutoverError)) else type(error).__name__
        )
        print(f"[ERROR] {detail}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
