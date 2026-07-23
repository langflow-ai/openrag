"""Heuristic scan for indirect-prompt-injection indicators (VULN-13906).

Advisory only: a match here doesn't mean a document is definitely malicious,
and a clean scan doesn't mean it's safe — this is a detection/audit signal
layered on top of the fencing (PR1), intent-gate (PR2), and allowlist/SSRF
(PR3) defenses, not a substitute for them. Non-blocking by default.
"""

from __future__ import annotations

import re

from utils.audit_helpers import write_audit_event_best_effort

# (indicator name, pattern). Deliberately narrow/high-signal — broad matches like
# a bare "---" line are far too common in ordinary markdown/YAML to be useful.
_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "ignore_instructions",
        re.compile(
            r"\b(ignore|disregard)\b[^.\n]{0,40}\b(previous|prior|above|all|system)\b[^.\n]{0,20}\binstructions?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "persona_override",
        re.compile(r"\byou are (now|actually)\b|\bact as\b(?!\s+a\s+helpful)", re.IGNORECASE),
    ),
    (
        "reveal_system_prompt",
        re.compile(r"\b(reveal|print|show|output)\b[^.\n]{0,20}\bsystem prompt\b", re.IGNORECASE),
    ),
    (
        "tool_call_directive",
        re.compile(
            r"\b(call|invoke|use|trigger)\b[^.\n]{0,30}\b(url ingestion|opensearch_url_ingestion_flow|url ingest)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "fetch_url_directive",
        re.compile(r"\b(fetch|retrieve|download)\b[^.\n]{0,20}\bhttps?://", re.IGNORECASE),
    ),
]


def scan_for_injection_indicators(text: str) -> list[str]:
    """Return the names of matched heuristic patterns, or [] if none matched."""
    if not text:
        return []
    return [name for name, pattern in _INJECTION_PATTERNS if pattern.search(text)]


async def audit_injection_indicators_detected(
    *,
    actor_user_id: str | None,
    target_id: str | None,
    filename: str | None,
    indicators: list[str],
) -> None:
    """Best-effort audit log write; must never raise (VULN-13906).

    Shared by the ingestion path (document_index_writer.py, per-chunk) and the
    chat-upload path (api/upload.py, whole-document) so both land the same
    event shape.
    """
    await write_audit_event_best_effort(
        event="document.injection_indicators_detected",
        actor_user_id=actor_user_id,
        target_type="document",
        target_id=target_id,
        audit_metadata={
            "filename": filename,
            "indicators": sorted(set(indicators)),
        },
    )
