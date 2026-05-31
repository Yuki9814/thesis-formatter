from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.content_analyzer import analyze_content
from core.format_extractor import extract_format_profile
from core.formatter_engine import format_docx
from core.report_generator import write_inspection_report, write_validation_report
from core.style_mapper import build_style_mapping
from core.validator import validate_output
from models import ContentStructure, FormatProfile, StyleMapping, ValidationIssue, ValidationResult
from models.io import load_model, write_model


def inspect_documents(
    template_path: str | Path,
    content_path: str | Path,
    out_dir: str | Path,
    rules_path: Optional[str | Path] = None,
) -> tuple[FormatProfile, ContentStructure, StyleMapping]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    profile = extract_format_profile(template_path)
    structure = analyze_content(content_path)
    mapping = build_style_mapping(profile, structure, rules_path=rules_path)
    write_model(out / "format_profile.json", profile)
    write_model(out / "content_structure.json", structure)
    write_model(out / "mapping.generated.json", mapping)
    write_inspection_report(out / "inspection_report.html", profile, structure, mapping)
    return profile, structure, mapping


def format_documents(
    template_path: str | Path,
    content_path: str | Path,
    mapping_path: str | Path,
    output_path: str | Path,
    report_path: str | Path,
    strict: bool = False,
    debug_dir: Optional[str | Path] = None,
) -> ValidationResult:
    profile = extract_format_profile(template_path)
    structure = analyze_content(content_path)
    mapping = load_model(mapping_path, StyleMapping)
    output = format_docx(
        template_path=template_path,
        content_path=content_path,
        output_path=output_path,
        structure=structure,
        mapping=mapping,
        profile=profile,
        strict=strict,
        debug_dir=debug_dir,
    )
    result = validate_output(output, profile, structure, mapping)
    report = Path(report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    write_validation_report(report, result)
    write_model(report.parent / "validation_result.json", result)
    return result


def validation_result_for_error(output_path: str | Path, exc: Exception) -> ValidationResult:
    return ValidationResult(
        output_path=str(output_path),
        passed=False,
        summary={"error": 1, "warning": 0, "info": 0},
        issues=[
            ValidationIssue(
                severity="error",
                code="format.failed",
                message=f"{type(exc).__name__}: {exc}",
                suggested_fix="Review mapping, input files, and debug artifacts.",
            )
        ],
    )

