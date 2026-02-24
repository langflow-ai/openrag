"""Unit tests for EnvManager file permission security.

These tests verify that every code path that writes a .env file enforces
0o600 (owner read/write only) permissions to prevent cleartext secret
exposure.  All tests use pytest's built-in ``tmp_path`` fixture and
``unittest.mock.patch``; no running infrastructure is required.
"""

import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Skip all tests on Windows — file permission model differs from Unix.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="Unix file permissions only"
)


def _perms(path: Path) -> int:
    """Return the permission bits of *path* as an integer (e.g. 0o600)."""
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.fixture
def env_manager(tmp_path):
    """EnvManager pointed at a temp directory (no real ~/.openrag I/O)."""
    from tui.managers.env_manager import EnvManager

    return EnvManager(env_file=tmp_path / ".env")


# ---------------------------------------------------------------------------
# save_env_file
# ---------------------------------------------------------------------------


class TestSaveEnvFilePermissions:
    """save_env_file must write the .env file with 0o600 permissions."""

    def test_new_file_creation_has_secure_permissions(self, env_manager, tmp_path):
        """A brand-new .env must be created with 0o600."""
        env_file = tmp_path / ".env"
        assert not env_file.exists(), "pre-condition: no .env yet"

        with patch("tui.utils.version_check.get_current_version", return_value="1.0.0"):
            result = env_manager.save_env_file()

        assert result is True
        assert env_file.exists()
        assert _perms(env_file) == 0o600, f"expected 0o600, got {oct(_perms(env_file))}"

    def test_overwrite_existing_file_has_secure_permissions(
        self, env_manager, tmp_path
    ):
        """Overwriting a permissive .env (0o644) must produce a new .env with 0o600."""
        env_file = tmp_path / ".env"
        env_file.write_text("OPENSEARCH_PASSWORD='old'\n")
        env_file.chmod(0o644)
        assert _perms(env_file) == 0o644, "pre-condition: file starts permissive"

        with patch("tui.utils.version_check.get_current_version", return_value="1.0.0"):
            result = env_manager.save_env_file()

        assert result is True
        assert env_file.exists()
        assert _perms(env_file) == 0o600, f"expected 0o600, got {oct(_perms(env_file))}"

    def test_backup_file_has_secure_permissions(self, env_manager, tmp_path):
        """The timestamped backup of a permissive .env (0o644) must be 0o600."""
        env_file = tmp_path / ".env"
        env_file.write_text("OPENSEARCH_PASSWORD='old'\n")
        env_file.chmod(0o644)

        with patch("tui.utils.version_check.get_current_version", return_value="1.0.0"):
            env_manager.save_env_file()

        # After save, the original .env was renamed to the backup; find it.
        backups = [f for f in tmp_path.iterdir() if f.name != ".env"]
        assert len(backups) == 1, (
            f"expected exactly 1 backup file, found: {[f.name for f in backups]}"
        )
        assert _perms(backups[0]) == 0o600, (
            f"expected 0o600, got {oct(_perms(backups[0]))}"
        )


# ---------------------------------------------------------------------------
# ensure_openrag_version
# ---------------------------------------------------------------------------


class TestEnsureOpenragVersionPermissions:
    """ensure_openrag_version must enforce 0o600 on every .env it touches."""

    def test_existing_file_update_has_secure_permissions(
        self, env_manager, tmp_path, monkeypatch
    ):
        """Updating OPENRAG_VERSION in a permissive .env (0o644) must set 0o600."""
        env_file = tmp_path / ".env"
        env_file.write_text("OPENSEARCH_PASSWORD='test'\n")
        env_file.chmod(0o644)
        assert _perms(env_file) == 0o644, "pre-condition: file starts permissive"

        # Prevent stale OPENRAG_VERSION in the process environment from
        # causing ensure_openrag_version to bail out early.
        monkeypatch.delenv("OPENRAG_VERSION", raising=False)

        with patch("tui.utils.version_check.get_current_version", return_value="1.2.3"):
            env_manager.ensure_openrag_version()

        assert env_file.exists()
        assert _perms(env_file) == 0o600, f"expected 0o600, got {oct(_perms(env_file))}"
        assert "OPENRAG_VERSION='1.2.3'" in env_file.read_text()

    def test_new_file_creation_has_secure_permissions(self, env_manager, tmp_path):
        """When no .env exists ensure_openrag_version must create one with 0o600."""
        env_file = tmp_path / ".env"
        assert not env_file.exists(), "pre-condition: no .env yet"

        with patch("tui.utils.version_check.get_current_version", return_value="1.2.3"):
            env_manager.ensure_openrag_version()

        assert env_file.exists()
        assert _perms(env_file) == 0o600, f"expected 0o600, got {oct(_perms(env_file))}"


# ---------------------------------------------------------------------------
# Legacy migration path (__init__)
# ---------------------------------------------------------------------------


class TestLegacyMigrationPermissions:
    """EnvManager.__init__ migration path must protect the copied .env with 0o600."""

    def test_migrated_file_has_secure_permissions(self, tmp_path):
        """A legacy .env (0o644) copied to the new location must get 0o600."""
        # Create the legacy file with deliberately permissive permissions.
        legacy_dir = tmp_path / "legacy_dir"
        legacy_dir.mkdir()
        legacy_env = legacy_dir / ".env"
        legacy_env.write_text("OPENSEARCH_PASSWORD='secret'\n")
        legacy_env.chmod(0o644)
        assert _perms(legacy_env) == 0o644, "pre-condition: legacy file is permissive"

        # Target path that does not yet exist; its parent will be created by
        # EnvManager.__init__ via Path.mkdir(parents=True, exist_ok=True).
        target_env = tmp_path / "new_location" / ".env"
        assert not target_env.exists(), "pre-condition: target not present"

        with (
            patch("utils.paths.get_tui_env_file", return_value=target_env),
            patch(
                "utils.paths.get_legacy_paths",
                return_value={"tui_env": legacy_env},
            ),
        ):
            from tui.managers.env_manager import EnvManager

            EnvManager()  # no explicit env_file — triggers the migration branch

        assert target_env.exists(), "migrated file must be present"
        assert _perms(target_env) == 0o600, (
            f"expected 0o600, got {oct(_perms(target_env))}"
        )
