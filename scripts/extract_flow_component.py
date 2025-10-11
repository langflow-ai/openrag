#!/usr/bin/env python3
"""
Extract embedded component code from a Langflow JSON flow.

Example:
    python scripts/extract_flow_component.py \\
        --flow-file flows/ingestion_flow.json \\
        --display-name "OpenSearch (Multi-Model)" \\
        --output flows/components/opensearch_multimodel.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Optional


def should_select_component(
    node: dict,
    *,
    display_name: Optional[str],
    metadata_module: Optional[str],
) -> bool:
    """Return True if the node matches the requested component filters."""
    node_data = node.get("data", {})
    component = node_data.get("node", {})

    if display_name and component.get("display_name") != display_name:
        return False

    if metadata_module:
        metadata = component.get("metadata", {})
        if metadata.get("module") != metadata_module:
            return False

    template = component.get("template", {})
    code_entry = template.get("code")
    return isinstance(code_entry, dict) and "value" in code_entry


def extract_code_from_flow(
    flow_path: Path,
    *,
    display_name: Optional[str],
    metadata_module: Optional[str],
    match_index: int,
) -> str:
    """Fetch the embedded code string from the matching component node."""
    try:
        flow_data = json.loads(flow_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"[error] failed to parse {flow_path}: {exc}") from exc

    matches = []
    for node in flow_data.get("data", {}).get("nodes", []):
        if should_select_component(
            node,
            display_name=display_name,
            metadata_module=metadata_module,
        ):
            matches.append(node)

    if not matches:
        raise SystemExit(
            "[error] no component found matching the supplied filters "
            f"in {flow_path}"
        )

    if match_index < 0 or match_index >= len(matches):
        raise SystemExit(
            f"[error] match index {match_index} out of range "
            f"(found {len(matches)} matches)"
        )

    target = matches[match_index]
    return target["data"]["node"]["template"]["code"]["value"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract component code from a Langflow JSON flow."
    )
    parser.add_argument(
        "--flow-file",
        required=True,
        type=Path,
        help="Path to the flow JSON file.",
    )
    parser.add_argument(
        "--display-name",
        help="Component display_name to match (e.g. 'OpenSearch (Multi-Model)').",
    )
    parser.add_argument(
        "--metadata-module",
        help="Component metadata.module value to match.",
    )
    parser.add_argument(
        "--match-index",
        type=int,
        default=0,
        help="Index of the matched component when multiple exist (default: 0).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Destination file for the extracted code (stdout if omitted).",
    )

    args = parser.parse_args()

    if not args.display_name and not args.metadata_module:
        # Offer an interactive selection of component display names
        if not args.flow_file.exists():
            parser.error(f"Flow file not found: {args.flow_file}")

        try:
            flow_data = json.loads(args.flow_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"[error] failed to parse {args.flow_file}: {exc}") from exc

        nodes = flow_data.get("data", {}).get("nodes", [])
        display_names = sorted(
            {
                node.get("data", {})
                .get("node", {})
                .get("display_name", "<unknown>")
                for node in nodes
            }
        )

        if not display_names:
            parser.error(
                "Unable to locate any components in the flow; supply --metadata-module instead."
            )

        print("Select a component display name:")
        for idx, name in enumerate(display_names):
            print(f"  [{idx}] {name}")

        while True:
            choice = input(f"Enter choice (0-{len(display_names)-1}): ").strip() or "0"
            if choice.isdigit():
                index = int(choice)
                if 0 <= index < len(display_names):
                    args.display_name = display_names[index]
                    break
            print("Invalid selection, please try again.")

    return args


def main() -> None:
    args = parse_args()

    if not args.flow_file.exists():
        raise SystemExit(f"[error] flow file not found: {args.flow_file}")

    code = extract_code_from_flow(
        args.flow_file,
        display_name=args.display_name,
        metadata_module=args.metadata_module,
        match_index=args.match_index,
    )

    if args.output:
        args.output.write_text(code, encoding="utf-8")
    else:
        print(code, end="")


if __name__ == "__main__":
    main()
