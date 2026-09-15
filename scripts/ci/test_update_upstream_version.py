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
            pages = [
                {"results": [{"name": "base-1.9.0"}, {"name": "base-2.0.0.dev1"}], "next": "page2"},
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
            releases = [{"tag_name": "3.7.0", "draft": False, "prerelease": False}]
            with patch.object(updater, "ROOT", root), patch.object(
                updater, "get_json", return_value=releases
            ), patch.object(updater, "opensearch_plugin_assets_exist", return_value=True):
                self.assertEqual(updater.update_opensearch(), ("3.6.0", "3.7.0"))
            self.assertIn("opensearch:3.7.0", (root / "Dockerfile").read_text())
            self.assertEqual((root / "Dockerfile").read_text().count("3.7.0.0"), 7)
            self.assertIn("opensearch-dashboards:3.7.0", (root / "docker-compose.yml").read_text())
            self.assertIn('tag: "3.7.0"', (root / "kubernetes/helm/openrag/values.yaml").read_text())

    def test_version_key_rejects_prereleases(self):
        with self.assertRaises(ValueError):
            updater.version_key("1.2.3rc1")


if __name__ == "__main__":
    unittest.main()
