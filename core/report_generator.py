from __future__ import annotations

import html
from pathlib import Path
from typing import Iterable

from models import ContentStructure, FormatProfile, StyleMapping, ValidationIssue, ValidationResult


CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #1f2937; }
h1, h2 { color: #111827; }
table { border-collapse: collapse; width: 100%; margin: 16px 0; }
th, td { border: 1px solid #d1d5db; padding: 8px; vertical-align: top; font-size: 14px; }
th { background: #f3f4f6; text-align: left; }
.error { color: #b91c1c; font-weight: 700; }
.warning { color: #b45309; font-weight: 700; }
.info { color: #1d4ed8; font-weight: 700; }
.ok { color: #047857; font-weight: 700; }
.muted { color: #6b7280; }
"""


def _page(title: str, body: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>{CSS}</style></head><body>{body}</body></html>"


def _safe(value: object) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def write_inspection_report(
    path: str | Path,
    profile: FormatProfile,
    structure: ContentStructure,
    mapping: StyleMapping,
) -> None:
    quality_class = "ok" if profile.template_quality.reliable_style_source else "warning"
    rows = []
    for entry in mapping.entries:
        rows.append(
            "<tr>"
            f"<td>{_safe(entry.role)}</td>"
            f"<td>{_safe(entry.style_name)} <span class='muted'>({_safe(entry.style_id)})</span></td>"
            f"<td>{entry.confidence:.2f}</td>"
            f"<td>{_safe(entry.source)}</td>"
            f"<td>{_safe(entry.warning)}</td>"
            "</tr>"
        )
    role_rows = "".join(
        f"<tr><td>{_safe(role)}</td><td>{count}</td></tr>" for role, count in sorted(structure.role_counts.items())
    )
    warnings = "".join(f"<li>{_safe(item)}</li>" for item in profile.template_quality.warnings)
    body = f"""
    <h1>Inspection Report</h1>
    <p>Template: {_safe(profile.source_path)}</p>
    <p>Content: {_safe(structure.source_path)}</p>
    <h2>Template Quality</h2>
    <p class="{quality_class}">{'Reliable style source' if profile.template_quality.reliable_style_source else 'Needs review'}</p>
    <ul>{warnings or '<li>No template quality warnings.</li>'}</ul>
    <table>
      <tr><th>Total paragraphs</th><th>Styled paragraphs</th><th>Direct paragraph formatting</th><th>Direct run formatting</th><th>Direct format ratio</th></tr>
      <tr><td>{profile.template_quality.total_paragraphs}</td><td>{profile.template_quality.styled_paragraphs}</td><td>{profile.template_quality.direct_paragraph_format_count}</td><td>{profile.template_quality.direct_run_format_count}</td><td>{profile.template_quality.direct_format_ratio:.3f}</td></tr>
    </table>
    <h2>Detected Content Roles</h2>
    <table><tr><th>Role</th><th>Count</th></tr>{role_rows}</table>
    <h2>Generated Mapping</h2>
    <table><tr><th>Role</th><th>Target style</th><th>Confidence</th><th>Source</th><th>Warning</th></tr>{''.join(rows)}</table>
    <h2>Advanced Features</h2>
    <pre>{_safe(structure.advanced_features)}</pre>
    """
    Path(path).write_text(_page("Inspection Report", body), encoding="utf-8")


def _issue_rows(issues: Iterable[ValidationIssue]) -> str:
    rows = []
    for issue in issues:
        rows.append(
            "<tr>"
            f"<td class='{_safe(issue.severity)}'>{_safe(issue.severity)}</td>"
            f"<td>{_safe(issue.code)}</td>"
            f"<td>{_safe(issue.paragraph_index)}</td>"
            f"<td>{_safe(issue.text_preview)}</td>"
            f"<td>{_safe(issue.current_style_name or issue.current_style_id)}</td>"
            f"<td>{_safe(issue.expected_style_name or issue.expected_style_id)}</td>"
            f"<td>{'' if issue.confidence is None else f'{issue.confidence:.2f}'}</td>"
            f"<td>{_safe(issue.message)}</td>"
            f"<td>{_safe(issue.suggested_fix)}</td>"
            "</tr>"
        )
    return "".join(rows)


def write_validation_report(path: str | Path, result: ValidationResult) -> None:
    status = "Passed" if result.passed else "Needs review"
    status_class = "ok" if result.passed else "warning"
    rows = _issue_rows(result.issues)
    body = f"""
    <h1>Validation Report</h1>
    <p>Output: {_safe(result.output_path)}</p>
    <p class="{status_class}">{status}</p>
    <h2>Summary</h2>
    <pre>{_safe(result.summary)}</pre>
    <h2>Issues</h2>
    <table>
      <tr><th>Severity</th><th>Code</th><th>Paragraph</th><th>Text preview</th><th>Current style</th><th>Expected style</th><th>Confidence</th><th>Message</th><th>Suggested fix</th></tr>
      {rows or '<tr><td colspan="9">No issues found.</td></tr>'}
    </table>
    """
    Path(path).write_text(_page("Validation Report", body), encoding="utf-8")

