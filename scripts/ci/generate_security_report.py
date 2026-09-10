#!/usr/bin/env python3
"""Generate a consolidated Security Scan Report from Trivy, Audit, and SAST JSON results.

Parses scan output JSON files produced by Trivy, pip-audit, npm audit, gosec,
and bandit, writing a unified Markdown report and summary table for GitHub Actions.
"""

import argparse
import csv
import json
import os
import sys
from pathlib import Path
from typing import Any

SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "UNKNOWN": 4}


def parse_trivy_json(path: Path) -> dict[str, Any]:
    """Parse Trivy JSON output for image or filesystem scan."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"Failed to parse {path.name}: {exc}"}

    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    findings: list[dict[str, str]] = []

    results = data.get("Results", []) or []
    for res in results:
        target = res.get("Target", "Unknown Target")
        vulns = res.get("Vulnerabilities", []) or []
        for v in vulns:
            sev = (v.get("Severity") or "UNKNOWN").upper()
            if sev in counts:
                counts[sev] += 1
            else:
                counts["UNKNOWN"] += 1

            findings.append(
                {
                    "target": target,
                    "id": v.get("VulnerabilityID", "N/A"),
                    "pkg": v.get("PkgName", "N/A"),
                    "installed": v.get("InstalledVersion", "N/A"),
                    "fixed": v.get("FixedVersion", "None"),
                    "severity": sev,
                    "title": (v.get("Title") or v.get("Description") or "").splitlines()[0][:100],
                }
            )

    return {"counts": counts, "findings": findings, "total": sum(counts.values())}


def parse_pip_audit_json(path: Path) -> dict[str, Any]:
    """Parse pip-audit JSON output."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"Failed to parse {path.name}: {exc}"}

    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    findings: list[dict[str, str]] = []

    # pip-audit outputs array of package results or dict with 'dependencies'
    packages = data if isinstance(data, list) else data.get("dependencies", [])
    for pkg in packages:
        name = pkg.get("name", "N/A")
        version = pkg.get("version", "N/A")
        vulns = pkg.get("vulns", []) or []
        for v in vulns:
            counts["HIGH"] += 1  # Default fallback for pip-audit findings
            findings.append(
                {
                    "target": f"{name}@{version}",
                    "id": v.get("id", "N/A"),
                    "pkg": name,
                    "installed": version,
                    "fixed": ", ".join(v.get("fix_versions", [])) or "None",
                    "severity": "HIGH",
                    "title": (v.get("description") or "").splitlines()[0][:100],
                }
            )

    return {"counts": counts, "findings": findings, "total": len(findings)}


def parse_npm_audit_json(path: Path) -> dict[str, Any]:
    """Parse npm audit JSON output."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"Failed to parse {path.name}: {exc}"}

    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    findings: list[dict[str, str]] = []

    metadata_counts = data.get("metadata", {}).get("vulnerabilities", {})
    if metadata_counts:
        counts["CRITICAL"] = metadata_counts.get("critical", 0)
        counts["HIGH"] = metadata_counts.get("high", 0)
        counts["MEDIUM"] = metadata_counts.get("moderate", 0)
        counts["LOW"] = metadata_counts.get("low", 0)

    vulnerabilities = data.get("vulnerabilities", {})
    for pkg_name, info in vulnerabilities.items():
        sev = (info.get("severity") or "UNKNOWN").upper()
        if sev == "MODERATE":
            sev = "MEDIUM"
        findings.append(
            {
                "target": pkg_name,
                "id": f"NPM-{pkg_name}",
                "pkg": pkg_name,
                "installed": info.get("range", "N/A"),
                "fixed": "See advisory",
                "severity": sev if sev in counts else "UNKNOWN",
                "title": f"Dependency advisory for {pkg_name}",
            }
        )

    return {"counts": counts, "findings": findings, "total": sum(counts.values())}


def parse_bandit_json(path: Path) -> dict[str, Any]:
    """Parse Bandit SAST JSON output."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"Failed to parse {path.name}: {exc}"}

    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    findings: list[dict[str, str]] = []

    results = data.get("results", []) or []
    for r in results:
        sev = (r.get("issue_severity") or "LOW").upper()
        if sev in counts:
            counts[sev] += 1
        else:
            counts["UNKNOWN"] += 1

        fname = Path(r.get("filename", "")).name
        line = r.get("line_number", "")
        findings.append(
            {
                "target": f"{fname}:{line}",
                "id": r.get("test_id", "SAST"),
                "pkg": r.get("test_name", "Bandit"),
                "installed": "N/A",
                "fixed": "Refactor code",
                "severity": sev,
                "title": r.get("issue_text", "")[:100],
            }
        )

    return {"counts": counts, "findings": findings, "total": sum(counts.values())}


def parse_gosec_json(path: Path) -> dict[str, Any]:
    """Parse Gosec SAST JSON output."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"Failed to parse {path.name}: {exc}"}

    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    findings: list[dict[str, str]] = []

    issues = data.get("Issues", []) or []
    for issue in issues:
        sev = (issue.get("severity") or "LOW").upper()
        if sev in counts:
            counts[sev] += 1
        else:
            counts["UNKNOWN"] += 1

        fname = Path(issue.get("file", "")).name
        line = issue.get("line", "")
        findings.append(
            {
                "target": f"{fname}:{line}",
                "id": issue.get("rule_id", "GOSEC"),
                "pkg": "gosec",
                "installed": "N/A",
                "fixed": "Refactor code",
                "severity": sev,
                "title": issue.get("details", "")[:100],
            }
        )

    return {"counts": counts, "findings": findings, "total": sum(counts.values())}


def collect_scan_results(
    report_dir: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Scan directory for JSON results and return structured scan data.

    Returns:
        (component_rows, all_findings, total_counts)
    """
    component_rows: list[dict[str, Any]] = []
    all_findings: list[dict[str, Any]] = []
    total_counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0, "TOTAL": 0}

    def _record_component(name: str, target: str, res: dict[str, Any]):
        if "error" in res:
            component_rows.append({"component": name, "target": target, "error": res["error"]})
            return

        c = res["counts"]
        tot = res["total"]
        component_rows.append(
            {
                "component": name,
                "target": target,
                "total": tot,
                "counts": c,
            }
        )
        for k in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"):
            total_counts[k] += c.get(k, 0)
        total_counts["TOTAL"] += tot

        for item in res.get("findings", []):
            item_copy = dict(item)
            item_copy["scanner"] = name
            all_findings.append(item_copy)

    # 1. Container Image Scans (Trivy)
    for json_file in sorted(report_dir.glob("trivy-image-*.json")):
        image_name = json_file.stem.replace("trivy-image-", "")
        res = parse_trivy_json(json_file)
        _record_component(f"Container Image ({image_name})", image_name, res)

    # 2. Filesystem / OSS Scans
    trivy_fs = report_dir / "trivy-fs.json"
    if trivy_fs.exists():
        res = parse_trivy_json(trivy_fs)
        _record_component("Repo Filesystem (Trivy FS)", "Repository", res)

    for json_file in sorted(report_dir.glob("pip-audit-*.json")):
        target_name = json_file.stem.replace("pip-audit-", "")
        res = parse_pip_audit_json(json_file)
        _record_component("Python Dependencies (`pip-audit`)", target_name, res)

    for json_file in sorted(report_dir.glob("npm-audit-*.json")):
        target_name = json_file.stem.replace("npm-audit-", "")
        res = parse_npm_audit_json(json_file)
        _record_component("Node.js Dependencies (`npm audit`)", target_name, res)

    # 3. SAST Scans
    bandit_file = report_dir / "bandit.json"
    if bandit_file.exists():
        res = parse_bandit_json(bandit_file)
        _record_component("Python SAST (`Bandit`)", "src/", res)

    gosec_file = report_dir / "gosec.json"
    if gosec_file.exists():
        res = parse_gosec_json(gosec_file)
        _record_component("Go SAST (`Gosec`)", "kubernetes/operator", res)

    # Sort all findings: CRITICAL -> HIGH -> MEDIUM -> LOW -> UNKNOWN
    all_findings.sort(
        key=lambda x: (
            SEVERITY_ORDER.get(x.get("severity", "UNKNOWN"), 5),
            x.get("scanner", ""),
            x.get("target", ""),
            x.get("id", ""),
        )
    )

    return component_rows, all_findings, total_counts


def generate_csv_report(findings: list[dict[str, Any]], output_path: Path) -> None:
    """Generate a comprehensive CSV report of all detected security findings."""
    fieldnames = [
        "Scanner",
        "Target",
        "Severity",
        "Vulnerability ID",
        "Package / Module",
        "Installed Version",
        "Fixed Version",
        "Title",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in findings:
            writer.writerow(
                {
                    "Scanner": item.get("scanner", "N/A"),
                    "Target": item.get("target", "N/A"),
                    "Severity": item.get("severity", "UNKNOWN"),
                    "Vulnerability ID": item.get("id", "N/A"),
                    "Package / Module": item.get("pkg", "N/A"),
                    "Installed Version": item.get("installed", "N/A"),
                    "Fixed Version": item.get("fixed", "None"),
                    "Title": item.get("title", ""),
                }
            )


def format_markdown_report(
    component_rows: list[dict[str, Any]],
    all_findings: list[dict[str, Any]],
    total_counts: dict[str, int],
    csv_filename: str | None = "security-report.csv",
) -> str:
    """Format Markdown report from collected scan results."""
    lines: list[str] = [
        "# 🛡️ OpenRAG Security Scan Report",
        "",
        "Consolidated security report generated across container images, OSS dependencies, and repo source code.",
        "",
        "## Executive Summary",
        "",
        "| Component / Scanner | Target | Total | Critical 🔴 | High 🟠 | Medium 🟡 | Low 🔵 |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: |",
    ]

    if not component_rows:
        lines.append("\n> [!NOTE]\n> No JSON scan results found in report directory.")
        return "\n".join(lines) + "\n"

    for row in component_rows:
        if "error" in row:
            lines.append(
                f"| {row['component']} | `{row['target']}` | Parse Error | - | - | - | - |"
            )
        else:
            c = row["counts"]
            lines.append(
                f"| {row['component']} | `{row['target']}` | {row['total']} | {c['CRITICAL']} | {c['HIGH']} | {c['MEDIUM']} | {c['LOW']} |"
            )

    # Total row
    lines.append(
        f"| **Total** | **All Scans** | **{total_counts['TOTAL']}** | **{total_counts['CRITICAL']}** | **{total_counts['HIGH']}** | **{total_counts['MEDIUM']}** | **{total_counts['LOW']}** |"
    )

    # CSV download callout
    lines.append("")
    if csv_filename:
        lines.append(
            f"> 📥 **Full Security Findings Export (CSV):** A comprehensive CSV report containing all **{len(all_findings)}** findings across all severities is available for download in the workflow **Artifacts** section (`security-report-csv` / `{csv_filename}`)."
        )
    lines.append("")

    # Filter critical and high findings for display table
    critical_high = [f for f in all_findings if f.get("severity") in ("CRITICAL", "HIGH")]

    lines.append("## 🚨 Top Vulnerabilities (Critical & High)")
    lines.append("")

    if not critical_high:
        lines.append("🎉 **No Critical or High severity vulnerabilities detected!**")
    else:
        lines.append(
            "| Severity | Scanner | Target | Vulnerability ID | Package / Module | Fixed Version | Title |"
        )
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for item in critical_high[:50]:  # Limit top 50 in summary
            sev_icon = "🔴 CRITICAL" if item["severity"] == "CRITICAL" else "🟠 HIGH"
            title = (item.get("title") or "").replace("|", "\\|")
            scanner = item.get("scanner", "N/A")
            lines.append(
                f"| {sev_icon} | {scanner} | `{item['target']}` | `{item['id']}` | `{item['pkg']}` | `{item['fixed']}` | {title} |"
            )

        if len(critical_high) > 50:
            lines.append("")
            lines.append(
                f"*Showing top 50 of {len(critical_high)} Critical & High findings. Download `{csv_filename}` for all {len(all_findings)} findings.*"
            )

    return "\n".join(lines) + "\n"


def generate_markdown_report(report_dir: Path, csv_filename: str = "security-report.csv") -> str:
    """Scan directory for JSON results and generate unified Markdown report."""
    component_rows, all_findings, total_counts = collect_scan_results(report_dir)
    return format_markdown_report(
        component_rows, all_findings, total_counts, csv_filename=csv_filename
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "directory",
        nargs="?",
        default="security-reports",
        help="Directory containing scan JSON result files (default: security-reports)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output path for the Markdown report (default: <directory>/security-report.md)",
    )
    parser.add_argument(
        "--csv-output",
        default=None,
        help="Output path for the CSV report (default: <directory>/security-report.csv)",
    )
    args = parser.parse_args()

    report_dir = Path(args.directory)
    output_md = Path(args.output) if args.output else report_dir / "security-report.md"
    output_csv = Path(args.csv_output) if args.csv_output else report_dir / "security-report.csv"

    component_rows, all_findings, total_counts = collect_scan_results(report_dir)
    report_md = format_markdown_report(
        component_rows, all_findings, total_counts, csv_filename=output_csv.name
    )

    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_md.write_text(report_md, encoding="utf-8")

    generate_csv_report(all_findings, output_csv)

    # Append to GitHub Step Summary if environment variable present
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write(report_md)

    print(f"Security Markdown report generated at: {output_md}")
    print(f"Security CSV report generated ({len(all_findings)} findings) at: {output_csv}")


if __name__ == "__main__":
    sys.exit(main())
