#!/usr/bin/env python3
"""Stamp bundled flow definitions with their OpenRAG release version."""

from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
from pathlib import Path

FLOW_VERSION_TAG_PREFIX = "openrag:flow-version:"


def _project_version(pyproject_path: Path) -> str:
    with pyproject_path.open("rb") as handle:
        version = tomllib.load(handle).get("project", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError(f"{pyproject_path} has no project.version")
    return version.strip()


def _flow_content_id(flow_data: dict) -> str:
    """Return a stable identifier for a flow, excluding an earlier release tag."""
    data = dict(flow_data)
    tags = data.get("tags", [])
    if isinstance(tags, list):
        data["tags"] = [
            tag
            for tag in tags
            if not isinstance(tag, str) or not tag.startswith(FLOW_VERSION_TAG_PREFIX)
        ]
    serialized = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(serialized.encode()).hexdigest()[:12]


def stamp_flow_version_tags(flows_directory: Path, pyproject_path: Path) -> list[Path]:
    """Replace the OpenRAG release tag on each bundled Langflow JSON flow."""
    version = _project_version(pyproject_path)
    updated_paths: list[Path] = []
    for flow_path in sorted(flows_directory.glob("*.json")):
        with flow_path.open(encoding="utf-8") as handle:
            flow_data = json.load(handle)

        # ``component_index.json`` is colocated with the flow definitions but
        # is an index payload, not a Langflow flow.
        if not isinstance(flow_data, dict) or not isinstance(flow_data.get("id"), str):
            continue

        tags = flow_data.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
            raise ValueError(f"{flow_path} has invalid flow tags")

        flow_data["tags"] = [
            *[tag for tag in tags if not tag.startswith(FLOW_VERSION_TAG_PREFIX)],
            f"{FLOW_VERSION_TAG_PREFIX}{version}:{_flow_content_id(flow_data)}",
        ]
        with flow_path.open("w", encoding="utf-8") as handle:
            json.dump(flow_data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        updated_paths.append(flow_path)

    return updated_paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flows-directory", type=Path, required=True)
    parser.add_argument("--pyproject", type=Path, required=True)
    args = parser.parse_args()

    updated_paths = stamp_flow_version_tags(args.flows_directory, args.pyproject)
    print(
        f"Stamped {len(updated_paths)} flow definitions with release {_project_version(args.pyproject)}"
    )


if __name__ == "__main__":
    main()
