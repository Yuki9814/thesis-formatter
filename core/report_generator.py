from __future__ import annotations

import html
from pathlib import Path
from typing import Iterable

from models import ContentStructure, FormatProfile, ReadinessResult, StyleMapping, ValidationIssue, ValidationResult


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
.summary { border: 1px solid #d1d5db; background: #f9fafb; padding: 16px; margin: 16px 0; }
.status { font-size: 22px; font-weight: 800; }
.high { color: #b91c1c; font-weight: 700; }
.medium { color: #b45309; font-weight: 700; }
.low { color: #047857; font-weight: 700; }
"""


def _page(title: str, body: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>{CSS}</style></head><body>{body}</body></html>"


def _safe(value: object) -> str:
    if value is None:
        return ""
    return html.escape(str(value))


def _list(items: list[str], empty: str) -> str:
    if not items:
        return f"<li>{_safe(empty)}</li>"
    return "".join(f"<li>{_safe(item)}</li>" for item in items)


def _readiness_block(readiness: ReadinessResult | None) -> str:
    if readiness is None:
        return ""
    return f"""
    <div class="summary">
      <div class="status {readiness.risk_level}">{_safe(readiness.status)}</div>
      <p>交付评分：<strong>{readiness.score}/100</strong>；风险等级：<strong class="{readiness.risk_level}">{_safe(readiness.risk_level)}</strong></p>
      <h2>阻塞项</h2>
      <ul>{_list(readiness.blocking_items, "没有阻塞项。")}</ul>
      <h2>人工复核项</h2>
      <ul>{_list(readiness.manual_review_items, "没有额外人工复核项。")}</ul>
      <h2>下一步</h2>
      <ul>{_list(readiness.next_actions, "保留报告，完成最终复核。")}</ul>
    </div>
    """


def _security_rows(findings) -> str:
    rows = []
    for finding in findings:
        rows.append(
            "<tr>"
            f"<td class='{_safe(finding.severity)}'>{_safe(finding.severity)}</td>"
            f"<td>{_safe(finding.code)}</td>"
            f"<td>{_safe(finding.part)}</td>"
            f"<td>{_safe(finding.message)}</td>"
            f"<td>{_safe(finding.suggested_fix)}</td>"
            "</tr>"
        )
    return "".join(rows)


def write_inspection_report(
    path: str | Path,
    profile: FormatProfile,
    structure: ContentStructure,
    mapping: StyleMapping,
    readiness: ReadinessResult | None = None,
) -> None:
    quality_class = "ok" if profile.template_quality.reliable_style_source else "warning"
    rows = []
    for entry in mapping.entries:
        samples = "<br>".join(_safe(item) for item in entry.sample_texts) or "<span class='muted'>No sample</span>"
        target_samples = "<br>".join(_safe(item) for item in entry.target_style_samples) or "<span class='muted'>No sample</span>"
        candidates = "<br>".join(
            f"{_safe(item.style_name)} <span class='muted'>({_safe(item.style_id)}, {item.score:.2f})</span>"
            for item in entry.candidate_styles[:3]
        )
        rows.append(
            "<tr>"
            f"<td>{_safe(entry.role)}</td>"
            f"<td>{_safe(entry.style_name)} <span class='muted'>({_safe(entry.style_id)})</span></td>"
            f"<td>{entry.confidence:.2f}</td>"
            f"<td>{_safe(entry.source)}</td>"
            f"<td>{_safe(entry.confidence_reason or entry.warning)}</td>"
            f"<td>{samples}</td>"
            f"<td>{target_samples}</td>"
            f"<td>{candidates}</td>"
            "</tr>"
        )
    role_rows = "".join(
        f"<tr><td>{_safe(role)}</td><td>{count}</td></tr>" for role, count in sorted(structure.role_counts.items())
    )
    warnings = "".join(f"<li>{_safe(item)}</li>" for item in profile.template_quality.warnings)
    security_rows = _security_rows([*profile.security_findings, *structure.security_findings])
    body = f"""
    <h1>Inspection Report</h1>
    {_readiness_block(readiness)}
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
    <table><tr><th>Role</th><th>Target style</th><th>Confidence</th><th>Source</th><th>Reason</th><th>Content samples</th><th>Style samples</th><th>Top candidates</th></tr>{''.join(rows)}</table>
    <h2>Advanced Features</h2>
    <pre>{_safe(structure.advanced_features)}</pre>
    <h2>Security Findings</h2>
    <table>
      <tr><th>Severity</th><th>Code</th><th>Part</th><th>Message</th><th>Suggested fix</th></tr>
      {security_rows or '<tr><td colspan="5">No security findings.</td></tr>'}
    </table>
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
    {_readiness_block(result.readiness)}
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


def write_delivery_checklist(path: str | Path, result: ValidationResult) -> None:
    readiness = result.readiness
    issues_by_severity = {}
    for issue in result.issues:
        issues_by_severity.setdefault(issue.severity, []).append(issue)
    issue_sections = []
    for severity in ("error", "warning", "info"):
        issues = issues_by_severity.get(severity, [])
        if not issues:
            continue
        issue_sections.append(
            f"<h2>{_safe(severity)}</h2><table>"
            "<tr><th>Code</th><th>Paragraph</th><th>Text preview</th><th>Message</th><th>Suggested fix</th></tr>"
            + "".join(
                "<tr>"
                f"<td>{_safe(issue.code)}</td>"
                f"<td>{_safe(issue.paragraph_index)}</td>"
                f"<td>{_safe(issue.text_preview)}</td>"
                f"<td>{_safe(issue.message)}</td>"
                f"<td>{_safe(issue.suggested_fix)}</td>"
                "</tr>"
                for issue in issues
            )
            + "</table>"
        )
    word_checks = [
        "用 Microsoft Word 打开输出文档，确认没有修复提示。",
        "更新目录、页码、交叉引用和其他域。",
        "检查封面、目录、正文首页、参考文献、附录的分页。",
        "逐处检查图片、表格、公式、脚注、尾注和页眉页脚。",
        "保存一份最终版，再导出 PDF 作为交付稿。",
    ]
    body = f"""
    <h1>交付检查清单</h1>
    {_readiness_block(readiness)}
    <h2>Word 内复核</h2>
    <ul>{_list(word_checks, "暂无复核项。")}</ul>
    <h2>问题分组</h2>
    {''.join(issue_sections) or '<p class="ok">没有报告问题。</p>'}
    """
    Path(path).write_text(_page("交付检查清单", body), encoding="utf-8")
