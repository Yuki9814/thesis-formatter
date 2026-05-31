from __future__ import annotations

from pathlib import Path

from core.report_generator import write_inspection_report, write_validation_report
from models import (
    ContentStructure,
    FormatProfile,
    MappingEntry,
    ReadinessResult,
    StyleMapping,
    TemplateQuality,
    ValidationIssue,
    ValidationResult,
)


def test_report_generator_html_escaping(tmp_path: Path) -> None:
    danger = "<script>alert(\"xss\")</script> & 'quoted'"

    profile = FormatProfile(
        source_path=danger,
        template_quality=TemplateQuality(warnings=[danger], reliable_style_source=False),
    )
    structure = ContentStructure(
        source_path=danger,
        role_counts={danger: 1},
        advanced_features={"key": danger},
    )
    mapping = StyleMapping(
        entries=[
            MappingEntry(
                role=danger,
                style_name=danger,
                style_id=danger,
                confidence=0.5,
                source=danger,
                warning=danger,
            )
        ]
    )
    readiness = ReadinessResult(
        status=danger,
        score=12,
        risk_level="high",
        blocking_items=[danger],
        manual_review_items=[danger],
        next_actions=[danger],
    )

    inspection_path = tmp_path / "inspection.html"
    write_inspection_report(inspection_path, profile, structure, mapping, readiness)
    inspection = inspection_path.read_text(encoding="utf-8")

    assert danger not in inspection
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt; &amp; &#x27;quoted&#x27;" in inspection

    result = ValidationResult(
        output_path=danger,
        passed=False,
        summary={danger: 1},
        readiness=readiness,
        issues=[
            ValidationIssue(
                severity=danger,
                code=danger,
                message=danger,
                paragraph_index=1,
                text_preview=danger,
                current_style_name=danger,
                expected_style_name=danger,
                suggested_fix=danger,
            )
        ],
    )

    validation_path = tmp_path / "validation.html"
    write_validation_report(validation_path, result)
    validation = validation_path.read_text(encoding="utf-8")

    assert danger not in validation
    assert "&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt; &amp; &#x27;quoted&#x27;" in validation


def test_report_generator_determinism(tmp_path: Path) -> None:
    profile = FormatProfile(
        source_path="template.docx",
        template_quality=TemplateQuality(
            warnings=["warning 1", "warning 2"],
            reliable_style_source=True,
            total_paragraphs=10,
            styled_paragraphs=8,
            direct_paragraph_format_count=1,
            direct_run_format_count=1,
            direct_format_ratio=0.2,
        ),
    )
    structure = ContentStructure(
        source_path="content.docx",
        role_counts={"body": 5, "heading_1": 1},
        advanced_features={"has_toc": True},
    )
    mapping = StyleMapping(
        entries=[
            MappingEntry(role="heading_1", style_name="Heading 1", style_id="h1", confidence=0.9),
            MappingEntry(role="body", style_name="Body Text", style_id="body", confidence=1.0),
        ]
    )

    inspection_a = tmp_path / "inspection-a.html"
    inspection_b = tmp_path / "inspection-b.html"
    write_inspection_report(inspection_a, profile, structure, mapping)
    write_inspection_report(inspection_b, profile, structure, mapping)

    assert inspection_a.read_bytes() == inspection_b.read_bytes()

    result = ValidationResult(
        output_path="output.docx",
        passed=True,
        summary={"error": 0, "warning": 1},
        issues=[
            ValidationIssue(
                severity="warning",
                code="W001",
                message="some message",
                paragraph_index=2,
                text_preview="text",
                current_style_name="Normal",
                expected_style_name="Body Text",
            )
        ],
    )

    validation_a = tmp_path / "validation-a.html"
    validation_b = tmp_path / "validation-b.html"
    write_validation_report(validation_a, result)
    write_validation_report(validation_b, result)

    assert validation_a.read_bytes() == validation_b.read_bytes()
