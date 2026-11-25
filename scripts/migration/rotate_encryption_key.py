"""Check, rotate, and verify an isolated OpenRAG restore without starting the app."""

import argparse
import asyncio
import base64
import json
import os
import re
import secrets
import stat
import sys
from collections import Counter
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import aiosqlite
import yaml
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from rotation_paths import overlaps
from sqlalchemy import Connection, MetaData, Table, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

# Match the on-disk format in src/utils/encryption.py without importing the
# target deployment's OpenRAG code. This folder can run on older checkouts.
ENCRYPTION_ALGORITHM = "AES-256-GCM"


def _derive_key(master_secret: str, salt: bytes) -> bytes:
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=100000).derive(
        master_secret.encode()
    )


def _encrypt_with_key(plaintext: str, master_secret: str, tenant: str) -> dict[str, Any]:
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    aad = f"tenant_id:{tenant}".encode()
    ciphertext = AESGCM(_derive_key(master_secret, salt)).encrypt(nonce, plaintext.encode(), aad)
    return {
        "version": "1.0",
        "algorithm": ENCRYPTION_ALGORITHM,
        "kdf": "PBKDF2HMAC-SHA256",
        "tenant_id": tenant,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
    }


def _decrypt_with_key(payload: dict[str, Any], master_secret: str, tenant: str) -> str:
    key = (
        _derive_key(master_secret, base64.b64decode(payload["salt"]))
        if "salt" in payload
        else base64.b64decode(master_secret)
    )
    plaintext = AESGCM(key).decrypt(
        base64.b64decode(payload["nonce"]),
        base64.b64decode(payload["ciphertext"]),
        f"tenant_id:{tenant}".encode(),
    )
    return plaintext.decode()


_DB_FIELDS = {
    "users": ("id", "user_pii", ("email", "display_name")),
    "user_preferences": (
        "user_id",
        "user_pref",
        ("agent_system_prompt_override", "provider_overrides", "preferences_json"),
    ),
    "workspace_config": ("section", "openrag", ("value",)),
    # Optional OpenSearch snapshot-import schema; its credentials use the default tenant.
    "snapshot_sources": ("id", "openrag", ("access_key_enc", "secret_key_enc")),
}
_CACHE_NAME = re.compile(
    r"(?:google_drive|onedrive|sharepoint)_(?:token(?:_.+)?|.+_[0-9a-f]{8})\.json"
)
_ENVELOPE_MARKER = re.compile(r'"(algorithm|ciphertext|nonce|salt|tenant_id|kdf)"\s*:')
_LEGACY_FILES = {Path("conversations.json"), Path("session_ownership.json")}
_CONNECTIONS = Path("connections.json")


class RotationError(Exception):
    """An operator-safe error. Never include stored values or supplied arguments."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        super().error("invalid arguments; see --help")


def _unique(pairs: list[tuple[Any, Any]]) -> dict[Any, Any]:
    result: dict[Any, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RotationError("Duplicate keys in a stored document.")
        result[key] = value
    return result


def _loads(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_unique)


class _ConfigLoader(yaml.SafeLoader):
    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        self.flatten_mapping(node)
        return _unique(self.construct_pairs(node, deep=deep))


def _looks_encrypted(value: Any) -> bool:
    return isinstance(value, dict) and (
        value.get("algorithm") == ENCRYPTION_ALGORITHM
        or (
            "ciphertext" in value
            and bool(value.keys() & {"nonce", "algorithm", "salt", "kdf", "tenant_id"})
        )
        or {"nonce", "salt", "kdf"} <= value.keys()
    )


def _decode_maybe(text: str, area: str) -> Any:
    try:
        return _loads(text)
    except json.JSONDecodeError:
        if text.lstrip().startswith("{") and (
            ENCRYPTION_ALGORITHM in text or len(set(_ENVELOPE_MARKER.findall(text))) >= 2
        ):
            raise RotationError(f"{area}: malformed encryption envelope.") from None
        return text  # legacy plaintext, including non-JSON token caches


class _Rotation:
    def __init__(self, read_key: str, write_key: str | None) -> None:
        self.read_key = read_key
        self.write_key = write_key
        self.counts: Counter[str] = Counter()

    def envelope(
        self,
        value: Any,
        tenant: str,
        area: str,
        transform: Callable[[str], str] | None = None,
    ) -> Any:
        if not _looks_encrypted(value):
            return value
        if value.get("tenant_id", tenant) != tenant:
            raise RotationError(f"{area}: tenant mismatch.")
        try:
            if value.get("algorithm") != ENCRYPTION_ALGORITHM:
                raise ValueError("Unsupported envelope algorithm.")
            plain = _decrypt_with_key(value, self.read_key, tenant)
        except Exception:
            raise RotationError(f"{area}: unreadable encryption envelope.") from None
        self.counts[area] += 1
        if transform is not None:
            plain = transform(plain)
        if self.write_key is None:
            return value
        # Keep any additional envelope metadata; upgrade legacy raw-key envelopes.
        return {**value, **_encrypt_with_key(plain, self.write_key, tenant)}

    def tree(self, value: Any, tenant: str, area: str) -> Any:
        if _looks_encrypted(value):
            return self.envelope(value, tenant, area)
        if isinstance(value, dict):
            changes = {}
            for key, item in value.items():
                updated = self.tree(item, tenant, area)
                if updated is not item:
                    changes[key] = updated
            if changes:
                return {**value, **changes}
        elif isinstance(value, list):
            updated_list = None
            for index, item in enumerate(value):
                updated = self.tree(item, tenant, area)
                if updated is not item:
                    if updated_list is None:
                        updated_list = value.copy()
                    updated_list[index] = updated
            if updated_list is not None:
                return updated_list
        return value


def _db_plan(conn: Connection, rotation: _Rotation) -> list[tuple[Table, str, Any, dict]]:
    updates = []
    db = inspect(conn)
    for name, (pk, tenant, fields) in _DB_FIELDS.items():
        if name == "snapshot_sources" and not db.has_table(name):
            continue
        table = Table(name, MetaData(), autoload_with=conn, resolve_fks=False)
        columns = [table.c[field] for field in fields]
        for row in conn.execute(select(table.c[pk], *columns)).mappings():
            changes = {}
            for field in fields:
                stored = row[field]
                area = f"{name}.{field}"
                if name == "workspace_config":
                    updated = rotation.tree(stored, tenant, area)
                    if updated is not stored:
                        changes[field] = updated
                elif stored:
                    payload = _decode_maybe(stored, area)
                    updated = rotation.envelope(payload, tenant, area)
                    if updated is not payload:
                        changes[field] = json.dumps(updated, separators=(",", ":"))
            if changes:
                updates.append((table, pk, row[pk], changes))
    return updates


def _root(path: Path) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise RotationError("Restore roots must be existing directories, not symlinks.")
    return path.resolve()


def _file(root: Path, relative: Path, *, required: bool = False) -> Path | None:
    # Check each component before reading, including broken symlinks and hardlinks.
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise RotationError("A restore file path escapes its copy root.")
    path = root
    for component in relative.parts:
        path /= component
        if path.is_symlink():
            raise RotationError("Symlinks are not allowed inside the restore.")
    try:
        info = path.stat()
    except FileNotFoundError:
        if required:
            raise RotationError("A required restore file is missing.") from None
        return None
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RotationError("Restore files must be regular files with no hardlinks.")
    return path


def _file_plan(
    args: argparse.Namespace, data: Path, config: Path, rotation: _Rotation
) -> dict[Path, str]:
    changes = {}
    tenant = args.tenant_id
    tokens = {Path(path): True for path in args.token_cache}
    explicit_paths = {Path(source): Path(target) for source, target in args.map_token_cache}
    if len(explicit_paths) != len(args.map_token_cache):
        raise RotationError("Duplicate token cache path mappings.")
    tokens.update(dict.fromkeys(explicit_paths.values(), True))
    for path in data.iterdir():
        if _CACHE_NAME.fullmatch(path.name):
            tokens.setdefault(Path(path.name), False)

    def connection_tokens(stored: str) -> None:
        path = Path(stored)
        if path in explicit_paths:
            return  # explicitly mapped paths are already in the inventory
        elif path.is_relative_to(args.data_dir.absolute()):
            tokens.setdefault(path.relative_to(args.data_dir.absolute()), False)
        elif path.is_relative_to(args.source_data_dir):
            tokens.setdefault(path.relative_to(args.source_data_dir), False)
        else:
            raise RotationError("connections.json: token path needs a restored-copy mapping.")

    def connections(document: Any) -> bool:
        records = document.get("connections") if isinstance(document, dict) else document
        if not isinstance(records, list):
            raise RotationError("connections.json: expected a list of connection records.")
        changed = False
        for record in records:
            if not isinstance(record, dict):
                raise RotationError("connections.json: invalid connection record.")
            settings = record.get("config", {})
            if not isinstance(settings, dict):
                raise RotationError("connections.json: invalid connector config.")
            stored = settings.get("token_file")
            if stored:
                if not isinstance(stored, str):
                    raise RotationError("connections.json: invalid token path.")
                connection_tokens(stored)
            owner = record.get("user_id") or "openrag"
            if not isinstance(owner, str):
                raise RotationError("connections.json: invalid connector tenant.")
            updated = rotation.tree(settings, owner, "connector config")
            if updated is not settings:
                record["config"] = updated
                changed = True
        return changed

    def inner_connections(text: str) -> str:
        document = _loads(text)
        return json.dumps(document, separators=(",", ":")) if connections(document) else text

    if path := _file(data, _CONNECTIONS):
        document = _loads(path.read_text(encoding="utf-8"))
        if _looks_encrypted(document):
            updated = rotation.envelope(document, tenant, "connections.json", inner_connections)
            changed = updated is not document
        else:
            updated = document
            changed = connections(document)
        if changed:
            changes[path] = json.dumps(updated, indent=2) + "\n"

    if path := _file(config, Path("config.yaml")):
        document = yaml.load(path.read_text(encoding="utf-8"), Loader=_ConfigLoader)
        if document is not None and not isinstance(document, dict):
            raise RotationError("config.yaml: expected a mapping.")
        if document and "providers" in document:
            updated = rotation.tree(document["providers"], "openrag", "config.yaml providers")
            if updated is not document["providers"]:
                changes[path] = yaml.safe_dump({**document, "providers": updated}, sort_keys=False)

    reserved = _LEGACY_FILES | {_CONNECTIONS}
    if args.sqlite is not None:
        reserved.add(args.sqlite.absolute().relative_to(args.data_dir.absolute()))
    if config.is_relative_to(data):
        reserved.add(config.relative_to(data) / "config.yaml")
    if tokens.keys() & reserved:
        raise RotationError("A token cache path overlaps another restore file.")
    for relative in sorted(tokens.keys() | _LEGACY_FILES):
        area = "OAuth token caches" if relative in tokens else "legacy state files"
        if path := _file(data, relative, required=tokens.get(relative, False)):
            payload = _decode_maybe(path.read_text(encoding="utf-8"), area)
            updated = rotation.envelope(payload, tenant, area)
            if updated is not payload:
                changes[path] = json.dumps(updated, indent=2) + "\n"
        elif relative in tokens:
            rotation.counts["absent OAuth cache paths"] += 1
    return changes


def _engine(args: argparse.Namespace, data: Path, *, apply: bool) -> AsyncEngine:
    if args.sqlite is not None:
        try:
            relative = args.sqlite.absolute().relative_to(args.data_dir.absolute())
        except ValueError:
            raise RotationError(
                "SQLite database must be inside the restored data directory."
            ) from None
        path = _file(data, relative, required=True)
        assert path is not None
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = path.with_name(path.name + suffix)
            if sidecar.exists() or sidecar.is_symlink():
                raise RotationError("SQLite restore has sidecars; restore a checkpointed backup.")
        # immutable=1 prevents check and verify from creating SQLite sidecars.
        uri = path.as_uri() + ("?mode=rw" if apply else "?mode=ro&immutable=1")

        async def connect() -> aiosqlite.Connection:
            return await aiosqlite.connect(uri, uri=True)

        return create_async_engine(
            "sqlite+aiosqlite://", async_creator=connect, json_deserializer=_loads
        )

    url = make_url(args.postgres_url_file.read_text(encoding="utf-8").rstrip("\r\n"))
    if not (
        url.drivername in {"postgresql", "postgresql+asyncpg"}
        and url.host in {"127.0.0.1", "::1"}
        and url.port
        and url.username
        and url.database
        and not url.query
    ):
        raise RotationError(
            "PostgreSQL requires an explicit loopback restore URL with no query options."
        )
    return create_async_engine(
        url.set(drivername="postgresql+asyncpg"),
        connect_args={"timeout": 10},
        json_deserializer=_loads,
        hide_parameters=True,
    )


async def _run(args: argparse.Namespace, rotation: _Rotation) -> None:
    data, config = _root(args.data_dir), _root(args.config_dir)
    apply = args.mode == "apply-to-copy"
    if apply:
        print(
            "[STEP] Checking that restore and original directories do not overlap.",
            file=sys.stderr,
        )
        originals = (args.original_data_dir, args.original_config_dir)
        if any(path is None or not path.is_absolute() for path in originals):
            raise RotationError("Apply requires absolute original data and config directory paths.")
        for original in originals:
            protected = original.resolve()
            if any(overlaps(root, protected) for root in (data, config)):
                raise RotationError("Restore directories must not overlap original directories.")
        print("[OK] Restore directories do not overlap the original directories.", file=sys.stderr)
    engine = _engine(args, data, apply=apply)
    try:
        async with engine.begin() as conn:
            if args.sqlite is not None and apply:
                await conn.exec_driver_sql("BEGIN IMMEDIATE")
            if args.postgres_url_file is not None:
                access = "READ WRITE" if apply else "READ ONLY"
                await conn.exec_driver_sql(
                    f"SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, {access}"
                )
            updates = await conn.run_sync(_db_plan, rotation)
            files = _file_plan(args, data, config, rotation)
            if apply:
                print(
                    f"[STEP] Staging {len(files)} file(s) with their existing owner, group, and mode.",
                    file=sys.stderr,
                )
                # Authenticate all inputs before touching any data. Stage every file before
                # committing the DB or replacing paths. Cross-store commit is not atomic.
                with ExitStack() as cleanup:
                    staged = []
                    for target, text in files.items():
                        original = target.stat()
                        with NamedTemporaryFile(dir=target.parent, delete=False) as output:
                            temp = Path(output.name)
                            cleanup.callback(temp.unlink, missing_ok=True)
                            output.write(text.encode())
                            output.flush()
                            fd = output.fileno()
                            staged_stat = os.fstat(fd)
                            if (staged_stat.st_uid, staged_stat.st_gid) != (
                                original.st_uid,
                                original.st_gid,
                            ):
                                try:
                                    os.fchown(fd, original.st_uid, original.st_gid)
                                except PermissionError:
                                    raise RotationError(
                                        "Cannot preserve restored file ownership; "
                                        "run with permission to preserve its owner and group."
                                    ) from None
                            os.fchmod(fd, stat.S_IMODE(original.st_mode))
                            os.fsync(fd)
                        staged.append((temp, target))
                    for table, pk, identity, values in updates:
                        await conn.execute(
                            table.update().where(table.c[pk] == identity).values(values)
                        )
                    for temp, target in staged:
                        temp.replace(target)
        if apply:
            print(
                f"[OK] Rotated {len(files)} file(s) without changing ownership or mode.",
                file=sys.stderr,
            )
            print(
                "[WARNING] Before cutover, confirm the backend can read the restored files.",
                file=sys.stderr,
            )
    finally:
        await engine.dispose()


def _key(path: Path, *, new: bool) -> str:
    value = path.read_text(encoding="utf-8").removesuffix("\n")
    if not value or "\n" in value or "\x00" in value:
        raise RotationError("Key files must contain exactly one non-empty key line.")
    if new:
        try:
            raw = base64.b64decode(value, validate=True)
        except ValueError:
            raise RotationError("Replacement key must be Base64 for exactly 32 bytes.") from None
        if len(raw) != 32 or base64.b64encode(raw).decode("ascii") != value:
            raise RotationError("Replacement key must be Base64 for exactly 32 bytes.")
    return value


def main() -> int:
    parser = _Parser(description=__doc__)
    parser.add_argument("mode", choices=("check", "apply-to-copy", "verify"))
    parser.add_argument("--data-dir", type=Path, required=True, help="data directory to inspect")
    parser.add_argument(
        "--config-dir", type=Path, required=True, help="config directory to inspect"
    )
    database = parser.add_mutually_exclusive_group(required=True)
    database.add_argument("--sqlite", type=Path, help="restored SQLite file inside --data-dir")
    database.add_argument(
        "--postgres-url-file", type=Path, help="file with the isolated PostgreSQL URL"
    )
    parser.add_argument("--old-key-file", type=Path, help="required for check and apply-to-copy")
    verify_key = parser.add_mutually_exclusive_group(required=True)
    verify_key.add_argument("--new-key-file", type=Path)
    verify_key.add_argument(
        "--key-file", type=Path, help="verify only: authenticate stored ciphertext with this key"
    )
    parser.add_argument(
        "--tenant-id", default="openrag", help="deployment tenant for encrypted files"
    )
    parser.add_argument(
        "--source-data-dir",
        type=Path,
        default=Path("data"),
        help="original data path as stored in connector token references",
    )
    for kind in ("data", "config"):
        parser.add_argument(
            f"--original-{kind}-dir",
            type=Path,
            help=f"absolute original {kind} path to protect (required for apply-to-copy)",
        )
    parser.add_argument(
        "--token-cache",
        action="append",
        default=[],
        metavar="COPY_PATH",
        help="extra OAuth cache path relative to --data-dir",
    )
    parser.add_argument(
        "--map-token-cache",
        action="append",
        default=[],
        nargs=2,
        metavar=("STORED_PATH", "COPY_PATH"),
        help="map a custom token reference to a path relative to --data-dir",
    )
    args = parser.parse_args()
    if (
        (args.mode == "verify") == (args.old_key_file is not None)
        or (args.key_file is not None and args.mode != "verify")
        or not args.tenant_id
    ):
        parser.error("invalid key or tenant arguments")
    try:
        if args.key_file is not None:
            rotation = _Rotation(_key(args.key_file, new=False), None)
        else:
            replacement = _key(args.new_key_file, new=True)
            previous = _key(args.old_key_file, new=False) if args.old_key_file is not None else None
            if previous == replacement:
                raise RotationError("Old and replacement keys must differ.")
            rotation = _Rotation(
                previous or replacement, replacement if args.mode == "apply-to-copy" else None
            )
        asyncio.run(_run(args, rotation))
        if args.key_file is not None and not rotation.counts.keys() - {"absent OAuth cache paths"}:
            raise RotationError("No ciphertext found; the key could not be authenticated.")
    except (Exception, KeyboardInterrupt) as error:
        # YAML/JSON, SQL, and crypto errors can contain values. Never render their text.
        detail = str(error) if isinstance(error, RotationError) else type(error).__name__
        print(f"{args.mode} failed: {detail}", file=sys.stderr)
        if args.mode == "apply-to-copy":
            print("Do not use this copy. Restore a fresh copy before retrying.", file=sys.stderr)
        return 1
    print(f"{args.mode} succeeded")
    for area, count in sorted(rotation.counts.items()):
        print(f"  {area}: {count}")
    if not rotation.counts.keys() - {"absent OAuth cache paths"}:
        print("  No ciphertext found; the key could not be authenticated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
