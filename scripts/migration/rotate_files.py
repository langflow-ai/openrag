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


def _unchanged(originals: list[Path], backups: list[Path]) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = originals[0].with_name(originals[0].name + suffix)
        if sidecar.exists() or sidecar.is_symlink():
            raise RotationError("SQLite sidecars found. Stop writers and checkpoint the database.")
    if any(_hash(a) != _hash(b) for a, b in zip(originals, backups, strict=True)):
        raise RotationError("Original files changed since backup; cutover refused.")


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
    parser.add_argument("mode", choices=("dry-run", "apply", "cutover"))
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--connections", type=Path, required=True)
    parser.add_argument(
        "--config-dir", type=Path, help="runtime config directory (defaults to data/config)"
    )
    parser.add_argument("--source-data-dir", type=Path)
    parser.add_argument("--tenant-id", default=os.getenv("OPENRAG_TENANT_ID") or "openrag")
    parser.add_argument("--old-key-file", type=Path)
    parser.add_argument("--new-key-file", type=Path, required=True)
    args = parser.parse_args()
    try:
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
        new = _key(args.new_key_file, new=True)
        if args.mode != "cutover":
            if args.old_key_file is None:
                raise RotationError("This command requires --old-key-file.")
            old = _key(args.old_key_file, new=False)
            if old == new:
                raise RotationError("Old and replacement keys must differ.")
            print(
                "[STEP] Checking the original SQLite database and connections read-only.",
                file=sys.stderr,
            )
            preflight = _Rotation(old, None)
            _inspect(args, parent, parent, preflight)
            if args.mode == "dry-run":
                for area, count in sorted(preflight.counts.items()):
                    print(f"{area}: {count}")
                return 0
            if any(path.exists() or path.is_symlink() for path in [*backups, *migrated, receipt]):
                raise RotationError("Rotation artifacts already exist; nothing was overwritten.")
            with TemporaryDirectory(prefix="openrag-file-rotation-") as temp:
                stage = Path(temp)
                files = [stage / path.name for path in originals]
                saved = [stage / path.name for path in backups]
                for original, backup, replica in zip(originals, saved, files, strict=True):
                    _copy(original, backup)
                    _copy(backup, replica)
                _unchanged(originals, saved)
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
                    json.dump([_hash(path) for path in [*saved, *files]], stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                _publish(parent, [*saved, *files, seal], [*backups, *migrated, receipt])
            print("[OK] Created .backup and .migrated files. Originals were not changed.")
            return 0
        if not sys.stdin.isatty():
            raise RotationError("Cutover requires an interactive terminal.")
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
