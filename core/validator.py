from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import List

from models import ContentStructure, FormatProfile, StyleMapping, ValidationIssue, ValidationResult

from .docx_loader import DocxError, list_parts, read_part, validate_docx_can_open, validate_docx_path
from .readiness import build_delivery_readiness
from .xml_utils import NS, attr, extract_style_map, has_direct_paragraph_format, parse_xml, paragraph_style_id


def _page_issue(profile: FormatProfile, output_root) -> List[ValidationIssue]:
    if not profile.sections:
        return []
    expected = profile.sections[-1]
    issues: List[ValidationIssue] = []
    sections = output_root.xpath(".//w:sectPr", namespaces=NS)
    if not sections:
        issues.append(
            ValidationIssue(
                severity="error",
                code="page.section_missing",
                message="Output document has no section properties.",
                suggested_fix="Open in Word and review page setup, or rerun formatting with a valid template.",
            )
        )
        return issues
    actual = sections[-1]
    pg_sz = actual.find("./w:pgSz", namespaces=NS)
    pg_mar = actual.find("./w:pgMar", namespaces=NS)
    comparisons = [
        ("page_width_twips", expected.page_width_twips, attr(pg_sz, "w:w") if pg_sz is not None else None),
        ("page_height_twips", expected.page_height_twips, attr(pg_sz, "w:h") if pg_sz is not None else None),
        ("margin_top_twips", expected.margin_top_twips, attr(pg_mar, "w:top") if pg_mar is not None else None),
        ("margin_bottom_twips", expected.margin_bottom_twips, attr(pg_mar, "w:bottom") if pg_mar is not None else None),
        ("margin_left_twips", expected.margin_left_twips, attr(pg_mar, "w:left") if pg_mar is not None else None),
        ("margin_right_twips", expected.margin_right_twips, attr(pg_mar, "w:right") if pg_mar is not None else None),
    ]
    for code, expected_value, actual_value in comparisons:
        if expected_value is not None and str(expected_value) != str(actual_value):
            issues.append(
                ValidationIssue(
                    severity="error",
                    code=f"page.{code}",
                    message=f"Expected {expected_value}, found {actual_value}.",
                    suggested_fix="Apply template page setup again.",
                )
            )
    return issues


def _advanced_feature_issues(structure: ContentStructure) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    features = structure.advanced_features
    messages = {
        "has_toc_field": "TOC fields were detected. MVP does not update fields automatically.",
        "has_cross_reference_fields": "Cross-reference fields were detected. MVP reports them instead of updating them.",
        "has_omml_equations": "OMML equations were detected and should be visually checked in Microsoft Word.",
        "has_footnotes": "Footnotes were detected and preserved at package level; review in Microsoft Word.",
        "has_endnotes": "Endnotes were detected and preserved at package level; review in Microsoft Word.",
        "has_bookmarks": "Bookmarks were detected and preserved; review cross-references in Microsoft Word.",
    }
    for key, message in messages.items():
        if features.get(key):
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code=f"advanced.{key}",
                    message=message,
                    suggested_fix="Validate final layout in Microsoft Word, preferably Windows Word.",
                )
            )
    return issues


def validate_output(
    output_path: str | Path,
    profile: FormatProfile,
    structure: ContentStructure,
    mapping: StyleMapping,
) -> ValidationResult:
    output = validate_docx_path(output_path)
    issues: List[ValidationIssue] = []
    try:
        validate_docx_can_open(output)
    except DocxError as exc:
        issues.append(
            ValidationIssue(
                severity="error",
                code="docx.open_failed",
                message=str(exc),
                suggested_fix="Inspect debug artifacts and regenerate the document.",
            )
        )
    root = parse_xml(read_part(output, "word/document.xml"))
    styles_root = parse_xml(read_part(output, "word/styles.xml"))
    names = extract_style_map(styles_root)
    entries = mapping.by_role()
    paragraphs = root.xpath(".//w:body//w:p", namespaces=NS)

    for warning in profile.template_quality.warnings:
        issues.append(
            ValidationIssue(
                severity="warning",
                code="template.quality",
                message=warning,
                suggested_fix="Prefer a clean Word template with reusable styles.",
            )
        )

    for finding in [*profile.security_findings, *structure.security_findings]:
        issues.append(
            ValidationIssue(
                severity=finding.severity,
                code=finding.code,
                message=finding.message,
                text_preview=finding.part,
                suggested_fix=finding.suggested_fix or "Review document security findings before delivery.",
            )
        )

    for entry in mapping.entries:
        if entry.required and not entry.style_id:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="mapping.missing",
                    message=f"No target style is mapped for role '{entry.role}'.",
                    expected_style_id=entry.style_id,
                    expected_style_name=entry.style_name,
                    confidence=entry.confidence,
                    suggested_fix="Edit mapping JSON and choose a valid target style.",
                )
            )
        elif entry.required and entry.confidence < mapping.low_confidence_threshold:
            issues.append(
                ValidationIssue(
                    severity="warning",
                    code="mapping.low_confidence",
                    message=f"Low-confidence mapping for role '{entry.role}'.",
                    expected_style_id=entry.style_id,
                    expected_style_name=entry.style_name,
                    confidence=entry.confidence,
                    suggested_fix="Confirm or edit the mapping before trusting the output.",
                )
            )

    for block in structure.blocks:
        entry = entries.get(block.role)
        if not entry or not entry.style_id or block.index >= len(paragraphs):
            continue
        actual_style_id = paragraph_style_id(paragraphs[block.index])
        if actual_style_id != entry.style_id:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="paragraph.style_mismatch",
                    message=f"Paragraph role '{block.role}' did not receive the expected style.",
                    paragraph_index=block.index,
                    text_preview=block.text_preview,
                    current_style_id=actual_style_id,
                    current_style_name=names.get(actual_style_id or ""),
                    expected_style_id=entry.style_id,
                    expected_style_name=entry.style_name,
                    confidence=entry.confidence,
                    suggested_fix="Review mapping and rerun formatting.",
                )
            )
        if has_direct_paragraph_format(paragraphs[block.index]):
            issues.append(
                ValidationIssue(
                    severity="info",
                    code="paragraph.direct_format",
                    message="Paragraph still has direct paragraph formatting.",
                    paragraph_index=block.index,
                    text_preview=block.text_preview,
                    current_style_id=actual_style_id,
                    current_style_name=names.get(actual_style_id or ""),
                    expected_style_id=entry.style_id,
                    expected_style_name=entry.style_name,
                    confidence=entry.confidence,
                    suggested_fix="Check whether this override is intentional.",
                )
            )

    issues.extend(_page_issue(profile, root))
    issues.extend(_advanced_feature_issues(structure))

    parts = list_parts(output)
    if structure.advanced_features.get("media_part_count", 0) and not any(name.startswith("word/media/") for name in parts):
        issues.append(
            ValidationIssue(
                severity="error",
                code="preserve.media_missing",
                message="Content document had media parts, but output has none.",
                suggested_fix="Inspect package relationships and regenerate from the original content document.",
            )
        )

    counts = Counter(issue.severity for issue in issues)
    summary = {"error": counts.get("error", 0), "warning": counts.get("warning", 0), "info": counts.get("info", 0)}
    return ValidationResult(
        output_path=str(output),
        passed=summary["error"] == 0,
        summary=summary,
        issues=issues,
        readiness=build_delivery_readiness(issues),
        security_findings=[*profile.security_findings, *structure.security_findings],
    )
