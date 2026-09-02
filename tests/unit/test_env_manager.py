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
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Unix file permissions only")


def _perms(path: Path) -> int:
    """Return the permission bits of *path* as an integer (e.g. 0o600)."""
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.fixture
def env_manager(tmp_path):
    """EnvManager pointed at a temp directory (no real ~/.bomarag I/O)."""
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

    def test_overwrite_existing_file_has_secure_permissions(self, env_manager, tmp_path):
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
        assert _perms(backups[0]) == 0o600, f"expected 0o600, got {oct(_perms(backups[0]))}"

    def test_preserves_unmanaged_env_variables(self, env_manager, tmp_path):
        """Saving config must keep existing .env keys that TUI does not manage."""
        env_file = tmp_path / ".env"
        env_file.write_text("BOMARAG_BACKEND_HOST='my-host'\nOPENSEARCH_PASSWORD='old-password'\n")

        env_manager.config.opensearch_password = "NewSecurePass!123"

        with patch("tui.utils.version_check.get_current_version", return_value="1.0.0"):
            result = env_manager.save_env_file()

        assert result is True
        content = env_file.read_text()
        assert "BOMARAG_BACKEND_HOST='my-host'" in content
        assert content.count("BOMARAG_BACKEND_HOST=") == 1
        assert "OPENSEARCH_PASSWORD='NewSecurePass!123'" in content
        assert "OPENSEARCH_PASSWORD='old-password'" not in content

    def test_preserves_unmanaged_multiline_quoted_value(self, env_manager, tmp_path):
        """Unmanaged python-dotenv–style multiline quoted values are preserved."""
        env_file = tmp_path / ".env"
        multiline_block = 'UNMANAGED_MULTILINE="line1\\nline2\\nline3"\n'
        env_file.write_text(multiline_block + 'OPENSEARCH_PASSWORD="old-password"\n')

        env_manager.config.opensearch_password = "NewSecurePass!456"

        with patch("tui.utils.version_check.get_current_version", return_value="1.0.0"):
            result = env_manager.save_env_file()

        assert result is True
        content = env_file.read_text()
        # Multiline unmanaged value should be preserved exactly once.
        assert multiline_block in content
        assert content.count("UNMANAGED_MULTILINE=") == 1
        # Managed password should be updated, not duplicated.
        assert "OPENSEARCH_PASSWORD='NewSecurePass!456'" in content
        assert "OPENSEARCH_PASSWORD='old-password'" not in content

    def test_preserves_unmanaged_continued_line(self, env_manager, tmp_path):
        """Unmanaged values using backslash continuation are preserved."""
        env_file = tmp_path / ".env"
        continued_block = "UNMANAGED_LONG_VALUE=first part \\\n  second part \\\n  third part\n"
        env_file.write_text(continued_block + 'OPENSEARCH_PASSWORD="old-password"\n')

        env_manager.config.opensearch_password = "AnotherNewPass!789"

        with patch("tui.utils.version_check.get_current_version", return_value="1.0.0"):
            result = env_manager.save_env_file()

        assert result is True
        content = env_file.read_text()
        # Continued-line unmanaged value should be preserved exactly once.
        assert continued_block in content
        assert content.count("UNMANAGED_LONG_VALUE=") == 1
        # Managed password should be updated, not duplicated.
        assert "OPENSEARCH_PASSWORD='AnotherNewPass!789'" in content
        assert 'OPENSEARCH_PASSWORD="old-password"' not in content


# ---------------------------------------------------------------------------
# ensure_bomarag_version
# ---------------------------------------------------------------------------


class TestEnsureBomaragVersionPermissions:
    """ensure_bomarag_version must enforce 0o600 on every .env it touches."""

    def test_existing_file_update_has_secure_permissions(self, env_manager, tmp_path, monkeypatch):
        """Updating BOMARAG_VERSION in a permissive .env (0o644) must set 0o600."""
        env_file = tmp_path / ".env"
        env_file.write_text("OPENSEARCH_PASSWORD='test'\n")
        env_file.chmod(0o644)
        assert _perms(env_file) == 0o644, "pre-condition: file starts permissive"

        # Prevent stale BOMARAG_VERSION in the process environment from
        # causing ensure_bomarag_version to bail out early.
        monkeypatch.delenv("BOMARAG_VERSION", raising=False)

        with patch("tui.utils.version_check.get_current_version", return_value="1.2.3"):
            env_manager.ensure_bomarag_version()

        assert env_file.exists()
        assert _perms(env_file) == 0o600, f"expected 0o600, got {oct(_perms(env_file))}"
        assert "BOMARAG_VERSION='1.2.3'" in env_file.read_text()

    def test_new_file_creation_has_secure_permissions(self, env_manager, tmp_path):
        """When no .env exists ensure_bomarag_version must create one with 0o600."""
        env_file = tmp_path / ".env"
        assert not env_file.exists(), "pre-condition: no .env yet"

        with patch("tui.utils.version_check.get_current_version", return_value="1.2.3"):
            env_manager.ensure_bomarag_version()

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
        assert _perms(target_env) == 0o600, f"expected 0o600, got {oct(_perms(target_env))}"


class TestLangflowPasswordAndAutoLogin:
    """Verify Langflow superuser password auto-generation, validation, and auto-login settings."""

    def test_setup_secure_defaults_generates_langflow_password_and_keeps_autologin(
        self, env_manager
    ):
        env_manager.config.langflow_superuser_password = ""
        env_manager.setup_secure_defaults()

        assert bool(env_manager.config.langflow_superuser_password)
        assert env_manager.config.langflow_auto_login == "True"
        assert env_manager.config.langflow_new_user_is_active == "True"
        assert env_manager.config.langflow_enable_superuser_cli == "True"

    def test_save_env_file_writes_langflow_password_and_autologin(self, env_manager, tmp_path):
        env_file = tmp_path / ".env"
        env_manager.config.opensearch_password = "OpenSearchPass123!"
        env_manager.config.langflow_superuser_password = "LangflowPass123!"

        with patch("tui.utils.version_check.get_current_version", return_value="1.0.0"):
            assert env_manager.save_env_file() is True

        content = env_file.read_text()
        assert "LANGFLOW_SUPERUSER_PASSWORD='LangflowPass123!'" in content
        assert "LANGFLOW_AUTO_LOGIN='True'" in content
        assert "LANGFLOW_SUPERUSER='langflow'" in content

    def test_validate_config_requires_langflow_password(self, env_manager):
        env_manager.config.opensearch_password = "Pass123!"
        env_manager.config.langflow_superuser_password = ""

        assert env_manager.validate_config() is False
        assert "langflow_superuser_password" in env_manager.config.validation_errors
