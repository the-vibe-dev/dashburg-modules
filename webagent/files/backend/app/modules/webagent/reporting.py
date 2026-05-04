from __future__ import annotations

import json
from typing import Any


def build_markdown_report(payload: dict[str, Any]) -> str:
    summary = str(payload.get("summary_text") or payload.get("summary") or "WebAgent run report")
    counts = payload.get("counts") if isinstance(payload.get("counts"), dict) else {}
    lines = [
        "# WebAgent Report",
        "",
        f"- Summary: {summary}",
        f"- Status: {payload.get('status', 'unknown')}",
    ]
    if counts:
        lines.append("- Coverage counts:")
        for k, v in counts.items():
            lines.append(f"  - {k}: {v}")
    warnings = payload.get("warnings") if isinstance(payload.get("warnings"), list) else []
    errors = payload.get("errors") if isinstance(payload.get("errors"), list) else []
    if warnings:
        lines.append("")
        lines.append("## Warnings")
        lines.extend([f"- {w}" for w in warnings])
    if errors:
        lines.append("")
        lines.append("## Errors")
        lines.extend([f"- {e}" for e in errors])
    return "\n".join(lines).strip() + "\n"


def build_machine_report(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "steps_attempted": payload.get("steps_attempted", []),
        "steps_succeeded": payload.get("steps_succeeded", []),
        "warnings": payload.get("warnings", []),
        "errors": payload.get("errors", []),
        "artifacts": payload.get("artifacts", []),
        "extracted_data": payload.get("extracted_data", {}),
        "summaries": payload.get("summaries", {}),
        "coverage_metrics": payload.get("coverage_metrics", {}),
    }


def dumps_report_json(payload: dict[str, Any]) -> str:
    return json.dumps(build_machine_report(payload), indent=2, ensure_ascii=False)
