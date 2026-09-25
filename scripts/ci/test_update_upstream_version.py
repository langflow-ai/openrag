"""Regression tests for the version proposal inputs and guarded edits."""

import tempfile
import unittest
from pathlib import Path
from shutil import copyfile
from unittest.mock import patch

import update_upstream_version as updater


class UpstreamVersionTests(unittest.TestCase):
    def test_langflow_ignores_prereleases_and_uses_semantic_order(self):
        with tempfile.TemporaryDirectory() as directory:
            dockerfile = Path(directory) / "Dockerfile.langflow"
            dockerfile.write_text("FROM langflowai/langflow:base-0.11.6\n")
            next_page = f"{updater.DOCKER_HUB_API}?page_size=100&name=base-&page=2"
            pages = [
                {"results": [{"name": "base-1.9.0"}, {"name": "base-2.0.0.dev1"}], "next": next_page},
                {"results": [{"name": "base-1.10.0"}, {"name": "latest"}], "next": None},
            ]
            with patch.object(updater, "ROOT", Path(directory)), patch.object(
                updater, "get_json", side_effect=pages
            ):
                self.assertEqual(updater.update_langflow(), ("0.11.6", "1.10.0"))
            self.assertEqual(dockerfile.read_text(), "FROM langflowai/langflow:base-1.10.0\n")

    def test_docling_changes_only_serve_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "src/tui/managers/docling_manager.py"
            path.parent.mkdir(parents=True)
            path.write_text('"docling-serve[ui]==1.26.0"\n"docling-core==2.85.0"\n')
            with patch.object(updater, "ROOT", Path(directory)), patch.object(
                updater, "get_json", return_value={"info": {"version": "1.32.0"}}
            ):
                self.assertEqual(updater.update_docling(), ("1.26.0", "1.32.0"))
            self.assertEqual(path.read_text(), '"docling-serve[ui]==1.32.0"\n"docling-core==2.85.0"\n')

    def test_docling_skips_prerelease(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "src/tui/managers/docling_manager.py"
            path.parent.mkdir(parents=True)
            path.write_text('"docling-serve[ui]==1.26.0"\n')
            with patch.object(updater, "ROOT", Path(directory)), patch.object(
                updater, "get_json", return_value={"info": {"version": "1.33.0rc1"}}
            ):
                self.assertIsNone(updater.update_docling())
            self.assertIn("1.26.0", path.read_text())

    def test_opensearch_skips_release_without_matching_plugin_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            dockerfile = Path(directory) / "Dockerfile"
            dockerfile.write_text("FROM opensearchproject/opensearch:3.6.0 AS upstream_opensearch\n")
            releases = [{"tag_name": "3.7.0", "draft": False, "prerelease": False}]
            with patch.object(updater, "ROOT", Path(directory)), patch.object(
                updater, "get_json", return_value=releases
            ), patch.object(updater, "opensearch_plugin_assets_exist", return_value=False):
                self.assertIsNone(updater.update_opensearch())
            self.assertIn("opensearch:3.6.0", dockerfile.read_text())

    def test_opensearch_updates_image_plugins_dashboards_and_docs(self):
        paths = (
            "Dockerfile",
            "docker-compose.yml",
            "kubernetes/helm/openrag/values.yaml",
            "docs/docs/get-started/docker.mdx",
            "docs/docs/reference/configuration.mdx",
            "docs/docs/support/troubleshoot.mdx",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in paths:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                copyfile(updater.ROOT / path, target)

            # Derive the current pin from the actual Dockerfile so the test
            # stays valid as the repo pin advances past 3.6.0.
            import re as _re
            dockerfile_text = (root / "Dockerfile").read_text()
            current_match = _re.search(
                r"FROM opensearchproject/opensearch:(\d+)\.(\d+)\.(\d+) ",
                dockerfile_text,
            )
            self.assertIsNotNone(current_match, "Could not find OpenSearch pin in Dockerfile")
            major, minor, patch_ = int(current_match.group(1)), int(current_match.group(2)), int(current_match.group(3))
            current = f"{major}.{minor}.{patch_}"
            next_ver = f"{major}.{minor}.{patch_ + 1}"

            releases = [{"tag_name": next_ver, "draft": False, "prerelease": False}]
            with patch.object(updater, "ROOT", root), patch.object(
                updater, "get_json", return_value=releases
            ), patch.object(updater, "opensearch_plugin_assets_exist", return_value=True):
                self.assertEqual(updater.update_opensearch(), (current, next_ver))
            self.assertIn(f"opensearch:{next_ver}", (root / "Dockerfile").read_text())
            self.assertEqual((root / "Dockerfile").read_text().count(f"{next_ver}.0"), 7)
            self.assertIn(f"opensearch-dashboards:{next_ver}", (root / "docker-compose.yml").read_text())
            self.assertIn(f'tag: "{next_ver}"', (root / "kubernetes/helm/openrag/values.yaml").read_text())

    def test_neural_search_asset_name_pre_370(self):
        """Versions before 3.7.0 use the old asset name without -jvector."""
        assets = {"opensearch-neural-search-3.6.0.0.zip", "artifacts.tar.gz", "prometheus-exporter-3.6.0.0.zip"}
        with patch.object(updater, "github_release_assets", return_value=assets):
            self.assertTrue(updater.opensearch_plugin_assets_exist("3.6.0"))

    def test_neural_search_asset_name_370_and_later(self):
        """Versions 3.7.0 and later require the -jvector suffix in the asset name."""
        # Old name should NOT satisfy the check for 3.7.0+
        old_assets = {"opensearch-neural-search-3.7.0.0.zip", "artifacts.tar.gz", "prometheus-exporter-3.7.0.0.zip"}
        with patch.object(updater, "github_release_assets", return_value=old_assets):
            self.assertFalse(updater.opensearch_plugin_assets_exist("3.7.0"))

        # New name should satisfy the check for 3.7.0+
        new_assets = {"opensearch-neural-search-jvector-3.7.0.0.zip", "artifacts.tar.gz", "prometheus-exporter-3.7.0.0.zip"}
        with patch.object(updater, "github_release_assets", return_value=new_assets):
            self.assertTrue(updater.opensearch_plugin_assets_exist("3.7.0"))

    def test_version_key_rejects_prereleases(self):
        with self.assertRaises(ValueError):
            updater.version_key("1.2.3rc1")


if __name__ == "__main__":
    unittest.main()
