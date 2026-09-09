import csv
import json
from pathlib import Path

import pytest

from scripts.ci.generate_security_report import (
    collect_scan_results,
    format_markdown_report,
    generate_csv_report,
    parse_bandit_json,
    parse_gosec_json,
    parse_npm_audit_json,
    parse_pip_audit_json,
    parse_trivy_json,
)


def test_parse_trivy_json(tmp_path):
    trivy_data = {
        "Results": [
            {
                "Target": "debian:12",
                "Vulnerabilities": [
                    {
                        "VulnerabilityID": "CVE-2024-0001",
                        "PkgName": "libcrypto",
                        "InstalledVersion": "1.0.0",
                        "FixedVersion": "1.0.1",
                        "Severity": "CRITICAL",
                        "Title": "Crypto flaw",
                    },
                    {
                        "VulnerabilityID": "CVE-2024-0002",
                        "PkgName": "libssl",
                        "InstalledVersion": "1.0.0",
                        "FixedVersion": "None",
                        "Severity": "HIGH",
                        "Description": "SSL issue",
                    },
                ],
            }
        ]
    }
    trivy_file = tmp_path / "trivy-image-backend.json"
    trivy_file.write_text(json.dumps(trivy_data), encoding="utf-8")

    res = parse_trivy_json(trivy_file)
    assert res["total"] == 2
    assert res["counts"]["CRITICAL"] == 1
    assert res["counts"]["HIGH"] == 1
    assert len(res["findings"]) == 2
    assert res["findings"][0]["id"] == "CVE-2024-0001"


def test_collect_and_generate_reports(tmp_path):
    # Setup mock scanner outputs
    trivy_file = tmp_path / "trivy-image-backend.json"
    trivy_file.write_text(
        json.dumps(
            {
                "Results": [
                    {
                        "Target": "backend:local",
                        "Vulnerabilities": [
                            {
                                "VulnerabilityID": "CVE-2024-1111",
                                "PkgName": "openssl",
                                "InstalledVersion": "1.1",
                                "FixedVersion": "1.2",
                                "Severity": "HIGH",
                                "Title": "OpenSSL bug",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    pip_file = tmp_path / "pip-audit-python.json"
    pip_file.write_text(
        json.dumps(
            [
                {
                    "name": "requests",
                    "version": "2.25.0",
                    "vulns": [
                        {
                            "id": "PYSEC-2023-1",
                            "fix_versions": ["2.31.0"],
                            "description": "Requests vuln",
                        }
                    ],
                }
            ]
        ),
        encoding="utf-8",
    )

    component_rows, all_findings, totals = collect_scan_results(tmp_path)
    assert len(component_rows) == 2
    assert totals["HIGH"] == 2
    assert totals["TOTAL"] == 2
    assert len(all_findings) == 2

    # Verify findings contain scanner tag
    scanners = {f["scanner"] for f in all_findings}
    assert "Container Image (backend)" in scanners
    assert "Python Dependencies (`pip-audit`)" in scanners

    # Test CSV Generation
    csv_file = tmp_path / "security-report.csv"
    generate_csv_report(all_findings, csv_file)
    assert csv_file.exists()

    with open(csv_file, newline="", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
        assert len(reader) == 2
        assert "Scanner" in reader[0]
        assert "Severity" in reader[0]
        assert "Vulnerability ID" in reader[0]
        assert "Fixed Version" in reader[0]

    # Test Markdown formatting
    md_content = format_markdown_report(
        component_rows, all_findings, totals, csv_filename="security-report.csv"
    )
    assert "Executive Summary" in md_content
    assert "| **Total** | **All Scans** |" in md_content
    assert "security-report-csv" in md_content
    assert "Top Vulnerabilities" in md_content
