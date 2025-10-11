#!/usr/bin/env python3
"""
Utility to sync embedded component code inside Langflow JSON files.

Given a Python source file (e.g. the OpenSearch component implementation) and
a target selector, this script updates every flow definition in ``./flows`` so
that the component's ``template.code.value`` matches the supplied file.

Example:
    python scripts/update_flow_components.py \\
        --code-file flows/components/opensearch_multimodel.py \\
        --display-name \"OpenSearch (Multi-Model)\"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable


def load_code(source_path: Path) -> str:
    try:
        return source_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise SystemExit(f"[error] code file not found: {source_path}") from exc


def should_update_component(node: dict, *, display_name: str | None, metadata_module: str | None) -> bool:
    node_data = node.get("data", {})
    component = node_data.get("node", {})

    if display_name and component.get("display_name") != display_name:
        return False

    if metadata_module:
        metadata = component.get("metadata", {})
        module_name = metadata.get("module")
        if module_name != metadata_module:
            return False

    template = component.get("template", {})
    code_entry = template.get("code")
    return isinstance(code_entry, dict) and "value" in code_entry


def update_flow(flow_path: Path, code: str, *, display_name: str | None, metadata_module: str | None, dry_run: bool) -> bool:
    with flow_path.open(encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"[error] failed to parse {flow_path}: {exc}") from exc

    changed = False

    for node in data.get("data", {}).get("nodes", []):
        if not should_update_component(node, display_name=display_name, metadata_module=metadata_module):
            continue

        template = node["data"]["node"]["template"]
        if template["code"]["value"] != code:
            if dry_run:
                changed = True
            else:
                template["code"]["value"] = code
                changed = True

    if changed and not dry_run:
        flow_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return changed


def iter_flow_files(flows_dir: Path) -> Iterable[Path]:
    for path in sorted(flows_dir.glob("*.json")):
        if path.is_file():
            yield path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update embedded component code in Langflow JSON files.")
    parser.add_argument("--code-file", required=True, type=Path, help="Path to the Python file containing the component code.")
    parser.add_argument("--flows-dir", type=Path, default=Path("flows"), help="Directory containing Langflow JSON files.")
    parser.add_argument("--display-name", help="Component display_name to match (e.g. 'OpenSearch (Multi-Model)').")
    parser.add_argument("--metadata-module", help="Component metadata.module value to match.")
    parser.add_argument("--dry-run", action="store_true", help="Report which files would change without modifying them.")

    args = parser.parse_args()

    if not args.display_name and not args.metadata_module:
        parser.error("At least one of --display-name or --metadata-module must be provided.")

    return args


def main() -> None:
    args = parse_args()

    flows_dir: Path = args.flows_dir
    if not flows_dir.exists():
        raise SystemExit(f"[error] flows directory not found: {flows_dir}")

    code = load_code(args.code_file)

    updated_files = []
    for flow_path in iter_flow_files(flows_dir):
        changed = update_flow(
            flow_path,
            code,
            display_name=args.display_name,
            metadata_module=args.metadata_module,
            dry_run=args.dry_run,
        )
        if changed:
            updated_files.append(flow_path)

    if args.dry_run:
        if updated_files:
            print("[dry-run] files that would be updated:")
            for path in updated_files:
                print(f"  - {path}")
        else:
            print("[dry-run] no files would change.")
    else:
        if updated_files:
            print("Updated component code in:")
            for path in updated_files:
                print(f"  - {path}")
        else:
            print("No updates were necessary.")


if __name__ == "__main__":
    main()
