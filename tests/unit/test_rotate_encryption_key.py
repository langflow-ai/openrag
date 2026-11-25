"""Operator-facing tests for offline OpenRAG key rotation."""

import base64
import json
import os
import pty
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from db.migrations_runtime import run_alembic_upgrade
from utils import encryption

OLD_KEY = base64.b64encode(b"a" * 32).decode()
NEW_KEY = base64.b64encode(b"b" * 32).decode()


@pytest.fixture
def restored_copy(tmp_path, monkeypatch):
    original_data = tmp_path / "original-data"
    original_config = tmp_path / "original-config"
    original_data.mkdir()
    original_config.mkdir()
    data_dir = tmp_path / "restored-data"
    config_dir = tmp_path / "restored-config"
    old_key_file = tmp_path / "old.key"
    new_key_file = tmp_path / "new.key"
    old_key_file.write_text(OLD_KEY + "\n")
    new_key_file.write_text(NEW_KEY + "\n")
    db = original_data / "openrag #copy.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db}")
    run_alembic_upgrade()
    monkeypatch.setattr(encryption, "_cached_master_secret", OLD_KEY)

    def restore():
        shutil.copytree(original_data, data_dir)
        shutil.copytree(original_config, config_dir)

        def run(mode, *extra, remove_old_key=False):
            if remove_old_key:
                old_key_file.unlink()
            env = os.environ.copy()
            env.pop("OPENRAG_ENCRYPTION_KEY", None)
            env.pop("DATABASE_URL", None)
            env.pop("PYTHONPATH", None)
            script = (
                Path(__file__).resolve().parents[2] / "scripts/migration/rotate_encryption_key.py"
            )
            args = [
                "--data-dir",
                str(data_dir),
                "--config-dir",
                str(config_dir),
                "--sqlite",
                str(data_dir / db.name),
                "--new-key-file",
                str(new_key_file),
                "--source-data-dir",
                str(original_data),
                "--tenant-id",
                "tenant",
            ]
            if mode == "apply-to-copy":
                args.extend(
                    (
                        "--original-data-dir",
                        str(original_data),
                        "--original-config-dir",
                        str(original_config),
                    )
                )
            if mode != "verify":
                args.extend(("--old-key-file", str(old_key_file)))
            return subprocess.run(
                [sys.executable, str(script), mode, *args, *extra],
                cwd=tmp_path,
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )

        return data_dir / db.name, data_dir, config_dir, run

    return db, original_data, original_config, restore


def test_rotates_a_restored_copy_without_changing_plaintext_or_row_metadata(
    restored_copy, monkeypatch
):
    db, original_data, original_config, restore = restored_copy
    encrypt = encryption.encrypt_secret
    config = original_config / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "providers": {
                    "custom": {
                        "test": {
                            "credentials": {
                                "password": encrypt("custom password"),
                                "location": "unchanged",
                            }
                        }
                    }
                }
            }
        )
    )
    cache = original_data / "named-cache.json"
    cache.write_text(json.dumps(encrypt('{"refresh_token":"saved refresh token"}', "tenant")))
    cache.chmod(0o640)
    # No salt in the original raw-key format; discover this unreferenced cache by name.
    nonce = b"\x00" * 12
    raw_ciphertext = AESGCM(base64.b64decode(OLD_KEY)).encrypt(
        nonce, b'{"legacy":true}', b"tenant_id:tenant"
    )
    legacy_cache = original_data / "onedrive_token_old.json"
    legacy_cache.write_text(
        json.dumps(
            {
                "algorithm": "AES-256-GCM",
                "nonce": base64.b64encode(nonce).decode(),
                "ciphertext": base64.b64encode(raw_ciphertext).decode(),
                "tenant_id": "tenant",
            }
        )
    )
    unrelated = original_data / "conversations.json"
    unrelated.write_text('{ "public data": ["unchanged"] }\n')
    connections = original_data / "connections.json"
    connections.write_text(
        json.dumps(
            {
                "connections": [
                    {
                        "user_id": "owner",
                        "connector_type": "uninstalled_plugin",
                        "config": {
                            "plugin_secret": encrypt("plugin credential", "owner"),
                            "token_file": str(cache),
                        },
                    }
                ]
            }
        )
    )
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO users (id, oauth_provider, oauth_subject, email, display_name, "
            "email_lookup_hash, created_at, updated_at) "
            "VALUES ('owner', 'google', 'subject', ?, 'plain name', 'lookup', "
            "'2026-01-01 00:00:00', '2026-01-02 00:00:00')",
            (json.dumps(encrypt("user@example.test", "user_pii")),),
        )
        conn.execute(
            "INSERT INTO user_preferences (user_id, provider_overrides, agent_system_prompt_override, "
            "preferences_json, updated_at) VALUES ('owner', ?, ?, ?, '2026-01-03 00:00:00')",
            tuple(
                json.dumps(encrypt(value, "user_pref"))
                for value in (
                    '{"openai":{"api_key":"personal"}}',
                    "saved system prompt",
                    '{"enabled":true}',
                )
            ),
        )
        conn.execute(
            "INSERT INTO workspace_config (section, value, updated_at, updated_by) "
            "VALUES ('connector_oauth', ?, '2026-01-01', 'owner')",
            (json.dumps({"google_drive": {"client_secret": encrypt("oauth secret")}}),),
        )
        # This optional table is present on the snapshot-import branch, not main.
        conn.execute(
            "CREATE TABLE snapshot_sources (id TEXT PRIMARY KEY, owner_user_id TEXT NOT NULL, "
            "name TEXT NOT NULL, endpoint_url TEXT, region TEXT NOT NULL, bucket TEXT NOT NULL, "
            "prefix TEXT NOT NULL, path_style BOOLEAN NOT NULL, verify_tls BOOLEAN NOT NULL, "
            "access_key_enc TEXT, secret_key_enc TEXT, created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL)"
        )
        conn.execute(
            "INSERT INTO snapshot_sources (id, owner_user_id, name, region, bucket, prefix, "
            "path_style, verify_tls, access_key_enc, secret_key_enc, created_at, updated_at) "
            "VALUES ('source', 'owner', 'name', 'us-east-1', 'bucket', '', 0, 1, ?, ?, "
            "'2026-01-04 00:00:00', '2026-01-05 00:00:00')",
            (json.dumps(encrypt("access")), json.dumps(encrypt("secret"))),
        )
    originals = {
        path: path.read_bytes()
        for path in (
            db,
            config,
            cache,
            legacy_cache,
            unrelated,
            connections,
        )
    }
    db, data_dir, config_dir, run = restore()
    config, cache, legacy_cache, connections = (
        config_dir / config.name,
        data_dir / cache.name,
        data_dir / legacy_cache.name,
        data_dir / connections.name,
    )
    before = {path: path.read_bytes() for path in (db, config, cache, legacy_cache, connections)}
    check = run("check")
    assert check.returncode == 0, check.stderr
    assert {path: path.read_bytes() for path in before} == before
    assert "OAuth token caches: 2" in check.stdout
    rejected = run("verify")
    assert rejected.returncode != 0
    assert "unreadable encryption envelope" in rejected.stderr

    apply = run("apply-to-copy")
    assert apply.returncode == 0, apply.stderr
    rotated = {path: path.read_bytes() for path in before}
    verify = run("verify", remove_old_key=True)
    assert verify.returncode == 0, verify.stderr
    assert verify.stdout.splitlines()[1:] == check.stdout.splitlines()[1:]
    assert {path: path.read_bytes() for path in rotated} == rotated
    assert {path: path.read_bytes() for path in originals} == originals
    assert (data_dir / unrelated.name).read_bytes() == originals[unrelated]
    assert cache.stat().st_mode & 0o777 == 0o640
    for result in (check, rejected, apply, verify):
        for private in (
            OLD_KEY,
            NEW_KEY,
            "plugin credential",
            "saved refresh token",
            "user@example.test",
        ):
            assert private not in result.stdout + result.stderr

    with pytest.raises(ValueError):
        encryption.decrypt_secret(json.loads(cache.read_text()))
    monkeypatch.setattr(encryption, "_cached_master_secret", NEW_KEY)
    decrypt = encryption.decrypt_secret
    assert json.loads(decrypt(json.loads(cache.read_text()), "tenant")) == {
        "refresh_token": "saved refresh token",
    }
    assert json.loads(decrypt(json.loads(legacy_cache.read_text()), "tenant")) == {"legacy": True}
    document = json.loads(connections.read_text())["connections"][0]["config"]
    assert decrypt(document["plugin_secret"], "owner") == "plugin credential"
    assert document["token_file"] == str(original_data / cache.name)
    credentials = yaml.safe_load(config.read_text())["providers"]["custom"]["test"]["credentials"]
    assert decrypt(credentials["password"]) == "custom password"
    assert credentials["location"] == "unchanged"
    with sqlite3.connect(db) as conn:
        email, *metadata = conn.execute(
            "SELECT email, display_name, email_lookup_hash, oauth_provider, oauth_subject, "
            "created_at, updated_at FROM users WHERE id = 'owner'"
        ).fetchone()
        assert decrypt(json.loads(email), "user_pii") == "user@example.test"
        assert metadata == [
            "plain name",
            "lookup",
            "google",
            "subject",
            "2026-01-01 00:00:00",
            "2026-01-02 00:00:00",
        ]
        overrides, prompt, preferences, updated_at = conn.execute(
            "SELECT provider_overrides, agent_system_prompt_override, preferences_json, "
            "updated_at FROM user_preferences"
        ).fetchone()
        assert updated_at == "2026-01-03 00:00:00"
        assert json.loads(decrypt(json.loads(overrides), "user_pref")) == {
            "openai": {"api_key": "personal"},
        }
        assert decrypt(json.loads(prompt), "user_pref") == "saved system prompt"
        assert json.loads(decrypt(json.loads(preferences), "user_pref")) == {"enabled": True}
        value, updated_at, updated_by = conn.execute(
            "SELECT value, updated_at, updated_by FROM workspace_config"
        ).fetchone()
        assert decrypt(json.loads(value)["google_drive"]["client_secret"]) == "oauth secret"
        assert (updated_at, updated_by) == ("2026-01-01", "owner")
        access, secret, *metadata = conn.execute(
            "SELECT access_key_enc, secret_key_enc, owner_user_id, bucket, created_at, updated_at "
            "FROM snapshot_sources"
        ).fetchone()
        assert (decrypt(json.loads(access)), decrypt(json.loads(secret))) == ("access", "secret")
        assert metadata == ["owner", "bucket", "2026-01-04 00:00:00", "2026-01-05 00:00:00"]


@pytest.mark.parametrize("mode", ["check", "apply-to-copy"])
@pytest.mark.parametrize(
    ("problem", "diagnostic"),
    [
        ("wrong_key", "unreadable encryption envelope"),
        ("wrong_tenant", "tenant mismatch"),
        ("malformed", "malformed encryption envelope"),
        ("linked", "Symlinks are not allowed"),
        ("hardlinked", "no hardlinks"),
    ],
)
def test_rejects_unsafe_cache_without_mutating_earlier_data(
    restored_copy, mode, problem, diagnostic
):
    db, original_data, original_config, restore = restored_copy
    config = original_config / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "providers": {
                    "openai": {
                        "api_key": encryption.encrypt_secret("provider secret"),
                    }
                }
            }
        )
    )
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO users (id, oauth_provider, oauth_subject, email, created_at, updated_at) "
            "VALUES ('owner', 'google', 'subject', ?, '2026-01-01', '2026-01-02')",
            (json.dumps(encryption.encrypt_secret("private@example.test", "user_pii")),),
        )
    cache = original_data / "sharepoint_token_test.json"
    if problem == "wrong_key":
        payload = encryption.encrypt_secret("refresh secret", "tenant")
        payload["ciphertext"] = base64.b64encode(b"cannot authenticate").decode()
        cache.write_text(json.dumps(payload))
    elif problem == "wrong_tenant":
        cache.write_text(json.dumps(encryption.encrypt_secret("refresh secret", "another-tenant")))
    elif problem == "malformed":
        cache.write_text('{"ciphertext":"refresh secret","algorithm":"AES-256-GCM"')
    restored_db, data, restored_config, run = restore()
    if problem == "linked":
        cache.write_text("{}")
        (data / cache.name).symlink_to(cache)
    elif problem == "hardlinked":
        cache.write_text("{}")
        os.link(cache, data / cache.name)
    paths = (db, config, cache, restored_db, restored_config / config.name, data / cache.name)
    before = {path: path.read_bytes() for path in paths}
    result = run(mode)
    assert result.returncode == 1
    assert diagnostic in result.stderr
    for private in (OLD_KEY, NEW_KEY, "refresh secret", "another-tenant", "private@example.test"):
        assert private not in result.stdout + result.stderr
    assert {path: path.read_bytes() for path in paths} == before


def test_rejects_connector_envelope_bound_to_another_owner(restored_copy):
    _, original_data, _, restore = restored_copy
    source = original_data / "connections.json"
    source.write_text(
        json.dumps(
            {
                "connections": [
                    {
                        "user_id": "expected-owner",
                        "config": {
                            "secret": encryption.encrypt_secret("credential", "different-owner")
                        },
                    }
                ]
            }
        )
    )
    _, data, _, run = restore()
    result = run("apply-to-copy")
    assert result.returncode == 1
    assert "connector config: tenant mismatch" in result.stderr
    assert "different-owner" not in result.stderr
    assert (data / source.name).read_bytes() == source.read_bytes()


@pytest.mark.parametrize("kind", ["data", "config", "alias"])
def test_apply_rejects_original_directory_with_relative_token_prefix(restored_copy, kind):
    db, original_data, original_config, restore = restored_copy
    path = original_config / "config.yaml"
    path.write_text("providers: {}\n")
    _, _, _, run = restore()
    before = db.read_bytes(), path.read_bytes()
    if kind == "alias":
        alias = original_data.with_name(original_data.name.upper())
        if not alias.exists():
            pytest.skip("filesystem is case-sensitive")
        result = run("apply-to-copy", "--data-dir", str(alias))
        assert result.returncode == 1
        assert "Restore directories must not overlap original directories" in result.stderr
        assert (db.read_bytes(), path.read_bytes()) == before
        return
    original = original_data if kind == "data" else original_config
    result = run("apply-to-copy", "--source-data-dir", "data", f"--{kind}-dir", str(original))
    assert result.returncode == 1
    assert "Restore directories must not overlap original directories" in result.stderr
    assert (db.read_bytes(), path.read_bytes()) == before


def test_file_rotation_keeps_originals_until_verified_cutover(restored_copy, monkeypatch):
    db, data, _, _ = restored_copy
    db = db.rename(data / "openrag.db")
    connections = data / "connections.json"
    payload = encryption.encrypt_secret("connector-secret")
    connections.write_text(json.dumps({"connections": [{"config": {"password": payload}}]}))
    connections.chmod(0o640)
    flow_dir = data / "flow-backups"
    flow_dir.mkdir()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "INSERT INTO workspace_config (section, value, updated_at) VALUES (?, ?, ?)",
            ("providers", json.dumps({"key": payload}), "2026-01-01"),
        )

    script = Path(__file__).resolve().parents[2] / "scripts/migration/rotate-key.sh"
    workspace = data.parent / "key-workspace"
    workspace.mkdir(mode=0o700)
    env = dict(
        os.environ,
        MIGRATION_PYTHON=sys.executable,
        OPENRAG_TENANT_ID="openrag",
        MIGRATION_DIR=str(workspace),
    )
    keys = subprocess.run(
        ["bash", str(script), "files", "keys"],
        input=f"{OLD_KEY}\n{NEW_KEY}\n",
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=20,
    )
    assert keys.returncode == 0, keys.stderr
    assert all(key not in keys.stdout + keys.stderr for key in (OLD_KEY, NEW_KEY))
    assert (workspace / "keys").stat().st_mode & 0o777 == 0o700
    for name, value in (("old", OLD_KEY), ("new", NEW_KEY)):
        path = workspace / "keys" / name
        assert path.read_text() == f"{value}\n"
        assert path.stat().st_mode & 0o777 == 0o600
    common = [
        "--sqlite",
        str(db),
        "--connections",
        str(connections),
    ]

    def run(mode, *key_args, stdin=None):
        return subprocess.run(
            [
                "bash",
                str(script),
                "files",
                mode,
                *common,
                *key_args,
            ],
            stdin=stdin,
            env=env,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    originals = (db, connections)
    before = [path.read_bytes() for path in originals]
    backups = [path.with_name(path.name + ".backup") for path in originals]
    migrated = [path.with_name(path.name + ".migrated") for path in originals]

    check = run("dry-run")
    assert check.returncode == 0, check.stderr
    assert not any(path.exists() for path in backups + migrated)
    backup = run("backup")
    assert backup.returncode == 0, backup.stderr
    assert [path.read_bytes() for path in backups] == before
    assert all(f"Backup saved: {str(path)!r}" in backup.stderr for path in backups)
    assert not any(path.exists() for path in migrated)
    repeated = run("backup")
    assert repeated.returncode == 1
    assert "nothing was overwritten" in repeated.stderr
    connections.write_bytes(before[1] + b"\n")
    stale = run("apply")
    assert stale.returncode == 1
    assert "Original files changed since backup" in stale.stderr
    assert not any(path.exists() for path in migrated)
    connections.write_bytes(before[1])
    apply = run("apply")
    assert apply.returncode == 0, apply.stderr
    assert [path.read_bytes() for path in originals] == before
    assert [path.read_bytes() for path in backups] == before
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in backups + migrated)
    assert all(f"Verified migrated file: {str(path)!r}" in apply.stderr for path in migrated)
    migrated_before = [path.read_bytes() for path in migrated]
    check = run("check", "--migrated")
    assert check.returncode == 0, check.stderr
    assert "workspace_config.value: 1" in check.stdout
    assert "connector config: 1" in check.stdout
    wrong = run("check", "--migrated", "--key-file", str(data.parent / "old.key"))
    assert wrong.returncode == 1
    assert "unreadable encryption envelope" in wrong.stderr
    assert [path.read_bytes() for path in migrated] == migrated_before

    def confirm():
        master, slave = pty.openpty()
        try:
            os.write(master, b"cutover-files\n")
            return run("cutover", stdin=slave)
        finally:
            os.close(slave)
            os.close(master)

    rotated_connections = migrated[1].read_bytes()
    migrated[1].write_text("{}")
    rejected = confirm()
    assert rejected.returncode == 1
    assert "changed since apply" in rejected.stderr
    assert [path.read_bytes() for path in originals] == before
    migrated[1].write_bytes(rotated_connections)

    result = confirm()
    assert result.returncode == 0, result.stderr
    assert "Backups remain in place." in result.stderr
    assert all(key not in result.stdout + result.stderr for key in (OLD_KEY, NEW_KEY))
    assert [path.read_bytes() for path in backups] == before
    assert [path.read_bytes() for path in originals] == [path.read_bytes() for path in migrated]
    assert flow_dir.is_dir()
    assert connections.stat().st_mode & 0o777 == 0o640
    check = run("check")
    assert check.returncode == 0, check.stderr
    monkeypatch.setattr(encryption, "_cached_master_secret", NEW_KEY)
    with sqlite3.connect(db) as conn:
        (value,) = conn.execute("SELECT value FROM workspace_config").fetchone()
    assert encryption.decrypt_secret(json.loads(value)["key"]) == "connector-secret"
    stored = json.loads(connections.read_text())["connections"][0]["config"]["password"]
    assert encryption.decrypt_secret(stored) == "connector-secret"
