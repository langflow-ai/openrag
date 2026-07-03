#!/usr/bin/env python3
"""Generate a concise Test Failure Report from JUnit XML results.

Scans a directory for `junit-*.xml` files (produced by `pytest --junitxml`
or `vitest --reporter=junit`) and writes a short Markdown summary listing
which tests failed and why, without dumping full service logs.
"""
import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

REDACT_PATTERNS = [
    (re.compile(r"Bearer [A-Za-z0-9._-]+"), "Bearer **REDACTED**"),
    (re.compile(r"token=[A-Za-z0-9._-]+"), "token=**REDACTED**"),
    (re.compile(r"sk-[A-Za-z0-9._-]+"), "sk-**REDACTED**"),
]


def redact(text: str) -> str:
    password = os.environ.get("OPENSEARCH_PASSWORD")
    if password:
        text = text.replace(password, "**REDACTED**")
    for pattern, replacement in REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def first_line(text: str, max_len: int = 300) -> str:
    text = text.strip()
    if not text:
        return ""
    text = text.splitlines()[0]
    return text[:max_len] + "..." if len(text) > max_len else text


def parse_junit_file(path: Path):
    tree = ET.parse(path)
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else root.findall(".//testsuite")

    totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    cases = []
    for suite in suites:
        for key in totals:
            totals[key] += int(suite.attrib.get(key, 0) or 0)
        for case in suite.findall("testcase"):
            failure = case.find("failure")
            error = case.find("error")
            problem = failure if failure is not None else error
            if problem is None:
                continue
            message = problem.attrib.get("message") or problem.text or ""
            cases.append(
                {
                    "classname": case.attrib.get("classname", ""),
                    "name": case.attrib.get("name", ""),
                    "message": redact(first_line(message)),
                }
            )
    return totals, cases


def build_report(directory: Path) -> str:
    junit_files = sorted(directory.glob("junit-*.xml"))
    lines = ["# Test Failure Report", ""]

    if not junit_files:
        lines.append("No JUnit result files found in `%s`." % directory)
        return "\n".join(lines) + "\n"

    any_failures = False
    for junit_file in junit_files:
        suite_name = junit_file.stem[len("junit-"):]
        lines.append(f"## {suite_name}")
        try:
            totals, cases = parse_junit_file(junit_file)
        except ET.ParseError as exc:
            lines.append(f"Could not parse `{junit_file.name}`: {exc}")
            lines.append("")
            continue

        lines.append(
            f"- Total: {totals['tests']}, "
            f"Failed: {totals['failures']}, "
            f"Errors: {totals['errors']}, "
            f"Skipped: {totals['skipped']}"
        )
        if cases:
            any_failures = True
            lines.append("")
            lines.append("| Test | Message |")
            lines.append("| --- | --- |")
            for case in cases:
                full_name = f"{case['classname']}::{case['name']}".strip(":")
                message = case["message"].replace("|", "\\|") or "(no message captured)"
                lines.append(f"| `{full_name}` | {message} |")
        lines.append("")

    if not any_failures:
        lines.append("All tests passed.")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory",
        nargs="?",
        default="service-logs",
        help="Directory containing junit-*.xml files (default: service-logs)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output path for the report (default: <directory>/test-failure-report.md)",
    )
    args = parser.parse_args()

    directory = Path(args.directory)
    output_path = Path(args.output) if args.output else directory / "test-failure-report.md"

    report = build_report(directory)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report)
    print(report)


if __name__ == "__main__":
    sys.exit(main())