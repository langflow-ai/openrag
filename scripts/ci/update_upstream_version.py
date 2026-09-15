"""Propose one compatible upstream service version bump per invocation.

The workflow runs this script separately for each service so a delayed plugin or
an incompatible dependency does not prevent unrelated upgrade PRs.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
GITHUB_API = "https://api.github.com"
DOCKER_HUB_API = "https://hub.docker.com/v2/repositories/langflowai/langflow/tags/"
PYPI_API = "https://pypi.org/pypi/docling-serve/json"
VERSION = re.compile(r"^(?:v)?(\d+)\.(\d+)\.(\d+)$")


def version_key(value: str) -> tuple[int, int, int]:
    match = VERSION.fullmatch(value)
    if not match:
        raise ValueError(f"Not a stable three-part version: {value}")
    return tuple(map(int, match.groups()))


def get_json(url: str) -> dict | list:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "openrag-version-updater"}
    if url.startswith(GITHUB_API) and os.environ.get("GH_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GH_TOKEN']}"
    try:
        with urlopen(Request(url, headers=headers), timeout=30) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not query {url}: {exc}") from exc


def replace_exact(path: str, old: str, new: str, count: int) -> None:
    file = ROOT / path
    content = file.read_text()
    actual = content.count(old)
    if actual != count:
        raise ValueError(f"Expected {count} occurrences of {old!r} in {path}, found {actual}")
    file.write_text(content.replace(old, new))


def github_release_assets(repo: str, tag: str) -> set[str]:
    release = get_json(f"{GITHUB_API}/repos/{repo}/releases/tags/{tag}")
    return {asset["name"] for asset in release["assets"]}


def opensearch_plugin_assets_exist(version: str) -> bool:
    plugin_version = f"{version}.0"
    expected = (
        ("opensearch-project/opensearch-jvector", "artifacts.tar.gz"),
        ("IBM/neural-search-jvector", f"opensearch-neural-search-{plugin_version}.zip"),
        (
            "opensearch-project/opensearch-prometheus-exporter",
            f"prometheus-exporter-{plugin_version}.zip",
        ),
    )
    for repo, asset in expected:
        try:
            if asset not in github_release_assets(repo, plugin_version):
                return False
        except RuntimeError as exc:
            # A missing release is expected while a plugin catches up. Other
            # API failures must fail the job rather than silently hide updates.
            if "HTTP Error 404" in str(exc):
                return False
            raise
    return True


def update_opensearch() -> tuple[str, str] | None:
    dockerfile = (ROOT / "Dockerfile").read_text()
    match = re.search(r"^FROM opensearchproject/opensearch:(\d+\.\d+\.\d+) ", dockerfile, re.M)
    if not match:
        raise ValueError("Could not find the OpenSearch base image pin")
    current = match.group(1)
    releases = get_json(f"{GITHUB_API}/repos/opensearch-project/OpenSearch/releases?per_page=100")
    candidates = sorted(
        (
            release["tag_name"].removeprefix("v")
            for release in releases
            if not release["draft"]
            and not release["prerelease"]
            and VERSION.fullmatch(release["tag_name"])
            and version_key(release["tag_name"]) > version_key(current)
        ),
        key=version_key,
        reverse=True,
    )
    for latest in candidates:
        if not opensearch_plugin_assets_exist(latest):
            print(f"Skipping OpenSearch {latest}: matching plugin assets are unavailable")
            continue
        replace_exact("Dockerfile", f"opensearch:{current}", f"opensearch:{latest}", 1)
        replace_exact("Dockerfile", f"{current}.0", f"{latest}.0", 7)
        replace_exact(
            "docker-compose.yml", f"opensearch-dashboards:{current}", f"opensearch-dashboards:{latest}", 1
        )
        replace_exact("kubernetes/helm/openrag/values.yaml", f'tag: "{current}"', f'tag: "{latest}"', 1)
        for path in (
            "docs/docs/get-started/docker.mdx",
            "docs/docs/reference/configuration.mdx",
            "docs/docs/support/troubleshoot.mdx",
        ):
            replace_exact(
                path,
                f"opensearch-dashboards:{current}",
                f"opensearch-dashboards:{latest}",
                (ROOT / path).read_text().count(f"opensearch-dashboards:{current}"),
            )
        return current, latest
    return None


def update_docling() -> tuple[str, str] | None:
    path = "src/tui/managers/docling_manager.py"
    content = (ROOT / path).read_text()
    match = re.search(r'"docling-serve\[ui\]==(\d+\.\d+\.\d+)"', content)
    if not match:
        raise ValueError("Could not find the Docling Serve pin")
    current = match.group(1)
    metadata = get_json(PYPI_API)
    latest = metadata["info"]["version"]
    if version_key(latest) <= version_key(current):
        return None
    replace_exact(path, f'"docling-serve[ui]=={current}"', f'"docling-serve[ui]=={latest}"', 1)
    return current, latest


def update_langflow() -> tuple[str, str] | None:
    path = "Dockerfile.langflow"
    content = (ROOT / path).read_text()
    match = re.search(r"^FROM langflowai/langflow:base-(\d+\.\d+\.\d+)$", content, re.M)
    if not match:
        raise ValueError("Could not find the Langflow base image pin")
    current = match.group(1)
    # Docker Hub's name filter narrows the listing to base-* tags. Iterate all
    # pages because tags are ordered by update time, not semantic version.
    url = f"{DOCKER_HUB_API}?page_size=100&name=base-"
    candidates: set[str] = set()
    while url:
        data = get_json(url)
        for tag in data["results"]:
            name = tag["name"]
            if name.startswith("base-") and VERSION.fullmatch(name[5:]):
                candidates.add(name[5:])
        url = data["next"]
    newer = [version for version in candidates if version_key(version) > version_key(current)]
    if not newer:
        return None
    latest = max(newer, key=version_key)
    replace_exact(path, f"langflow:base-{current}", f"langflow:base-{latest}", 1)
    return current, latest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("component", choices=("opensearch", "docling", "langflow"))
    args = parser.parse_args()
    result = {
        "opensearch": update_opensearch,
        "docling": update_docling,
        "langflow": update_langflow,
    }[args.component]()
    if result:
        current, latest = result
        print(f"{args.component}: {current} -> {latest}")
    else:
        current = latest = ""
        print(f"{args.component}: no compatible newer version found")
    if output := os.environ.get("GITHUB_OUTPUT"):
        with open(output, "a") as file:
            file.write(f"changed={'true' if result else 'false'}\ncurrent={current}\nlatest={latest}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
