#!/usr/bin/env python3
"""Generate a consolidated Security Scan Report from Trivy, Audit, and SAST JSON results.

Parses scan output JSON files produced by Trivy, pip-audit, npm audit, gosec,
and bandit, writing a unified Markdown report and summary table for GitHub Actions.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Any


def parse_trivy_json(path: Path) -> Dict[str, Any]:
    """Parse Trivy JSON output for image or filesystem scan."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"Failed to parse {path.name}: {exc}"}

    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    findings: List[Dict[str, str]] = []

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


def parse_pip_audit_json(path: Path) -> Dict[str, Any]:
    """Parse pip-audit JSON output."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"Failed to parse {path.name}: {exc}"}

    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    findings: List[Dict[str, str]] = []

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


def parse_npm_audit_json(path: Path) -> Dict[str, Any]:
    """Parse npm audit JSON output."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"Failed to parse {path.name}: {exc}"}

    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    findings: List[Dict[str, str]] = []

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


def parse_bandit_json(path: Path) -> Dict[str, Any]:
    """Parse Bandit SAST JSON output."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"Failed to parse {path.name}: {exc}"}

    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    findings: List[Dict[str, str]] = []

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


def parse_gosec_json(path: Path) -> Dict[str, Any]:
    """Parse Gosec SAST JSON output."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"error": f"Failed to parse {path.name}: {exc}"}

    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    findings: List[Dict[str, str]] = []

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


def generate_markdown_report(report_dir: Path) -> str:
    """Scan directory for JSON results and generate unified Markdown report."""
    lines: List[str] = [
        "# 🛡️ OpenRAG Security Scan Report",
        "",
        "Consolidated security report generated across container images, OSS dependencies, and repo source code.",
        "",
        "## Executive Summary",
        "",
        "| Component / Scanner | Target | Total | Critical 🔴 | High 🟠 | Medium 🟡 | Low 🔵 |",
        "| :--- | :--- | :---: | :---: | :---: | :---: | :---: |",
    ]

    all_findings: List[Dict[str, str]] = []
    has_scans = False

    # Process Container Image Scans (Trivy)
    for json_file in sorted(report_dir.glob("trivy-image-*.json")):
        has_scans = True
        image_name = json_file.stem.replace("trivy-image-", "")
        res = parse_trivy_json(json_file)
        if "error" in res:
            lines.append(f"| Container Image ({image_name}) | `{image_name}` | Parse Error | - | - | - | - |")
            continue
        c = res["counts"]
        lines.append(
            f"| Container Image (`{image_name}`) | `{image_name}` | {res['total']} | {c['CRITICAL']} | {c['HIGH']} | {c['MEDIUM']} | {c['LOW']} |"
        )
        all_findings.extend(res.get("findings", []))

    # Process Filesystem / OSS Scans
    trivy_fs = report_dir / "trivy-fs.json"
    if trivy_fs.exists():
        has_scans = True
        res = parse_trivy_json(trivy_fs)
        if "counts" in res:
            c = res["counts"]
            lines.append(f"| Repo Filesystem (Trivy FS) | Repository | {res['total']} | {c['CRITICAL']} | {c['HIGH']} | {c['MEDIUM']} | {c['LOW']} |")
            all_findings.extend(res.get("findings", []))

    for json_file in sorted(report_dir.glob("pip-audit-*.json")):
        has_scans = True
        target_name = json_file.stem.replace("pip-audit-", "")
        res = parse_pip_audit_json(json_file)
        if "counts" in res:
            c = res["counts"]
            lines.append(f"| Python Dependencies (`pip-audit`) | `{target_name}` | {res['total']} | {c['CRITICAL']} | {c['HIGH']} | {c['MEDIUM']} | {c['LOW']} |")
            all_findings.extend(res.get("findings", []))

    for json_file in sorted(report_dir.glob("npm-audit-*.json")):
        has_scans = True
        target_name = json_file.stem.replace("npm-audit-", "")
        res = parse_npm_audit_json(json_file)
        if "counts" in res:
            c = res["counts"]
            lines.append(f"| Node.js Dependencies (`npm audit`) | `{target_name}` | {res['total']} | {c['CRITICAL']} | {c['HIGH']} | {c['MEDIUM']} | {c['LOW']} |")
            all_findings.extend(res.get("findings", []))

    # Process SAST Scans
    bandit_file = report_dir / "bandit.json"
    if bandit_file.exists():
        has_scans = True
        res = parse_bandit_json(bandit_file)
        if "counts" in res:
            c = res["counts"]
            lines.append(f"| Python SAST (`Bandit`) | `src/` | {res['total']} | {c['CRITICAL']} | {c['HIGH']} | {c['MEDIUM']} | {c['LOW']} |")
            all_findings.extend(res.get("findings", []))

    gosec_file = report_dir / "gosec.json"
    if gosec_file.exists():
        has_scans = True
        res = parse_gosec_json(gosec_file)
        if "counts" in res:
            c = res["counts"]
            lines.append(f"| Go SAST (`Gosec`) | `kubernetes/operator` | {res['total']} | {c['CRITICAL']} | {c['HIGH']} | {c['MEDIUM']} | {c['LOW']} |")
            all_findings.extend(res.get("findings", []))

    if not has_scans:
        lines.append("\n> [!NOTE]\n> No JSON scan results found in report directory.")
        return "\n".join(lines) + "\n"

    # Filter critical and high findings for display table
    critical_high = [f for f in all_findings if f.get("severity") in ("CRITICAL", "HIGH")]

    lines.append("")
    lines.append("## 🚨 Top Vulnerabilities (Critical & High)")
    lines.append("")

    if not critical_high:
        lines.append("🎉 **No Critical or High severity vulnerabilities detected!**")
    else:
        lines.append("| Severity | Target | Vulnerability ID | Package / Module | Fixed Version | Title |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for item in critical_high[:50]:  # Limit top 50
            sev_icon = "🔴 CRITICAL" if item["severity"] == "CRITICAL" else "🟠 HIGH"
            title = item["title"].replace("|", "\\|")
            lines.append(
                f"| {sev_icon} | `{item['target']}` | `{item['id']}` | `{item['pkg']}` | `{item['fixed']}` | {title} |"
            )

    return "\n".join(lines) + "\n"


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
    args = parser.parse_args()

    report_dir = Path(args.directory)
    output_path = Path(args.output) if args.output else report_dir / "security-report.md"

    report_md = generate_markdown_report(report_dir)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_md, encoding="utf-8")

    # Append to GitHub Step Summary if environment variable present
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write(report_md)

    print(f"Security report successfully generated at: {output_path}")


if __name__ == "__main__":
    sys.exit(main())
