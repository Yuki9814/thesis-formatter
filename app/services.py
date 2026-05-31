from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Optional

from core.content_analyzer import analyze_content
from core.docx_loader import validate_docx_path
from core.format_extractor import extract_format_profile
from core.formatter_engine import format_docx
from core.readiness import build_inspection_readiness, readiness_for_failure
from core.report_generator import write_delivery_checklist, write_inspection_report, write_validation_report
from core.style_mapper import build_style_mapping
from core.validator import validate_output
from models import ContentStructure, DoctorCheck, DoctorResult, FormatProfile, StyleMapping, ValidationIssue, ValidationResult
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
    readiness = build_inspection_readiness(profile, structure, mapping)
    write_model(out / "format_profile.json", profile)
    write_model(out / "content_structure.json", structure)
    write_model(out / "mapping.generated.json", mapping)
    write_model(out / "readiness_result.json", readiness)
    write_inspection_report(out / "inspection_report.html", profile, structure, mapping, readiness)
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
    if result.readiness:
        write_model(report.parent / "delivery_checklist.json", result.readiness)
    write_delivery_checklist(report.parent / "delivery_checklist.html", result)
    return result


def validation_result_for_error(output_path: str | Path, exc: Exception) -> ValidationResult:
    message = f"{type(exc).__name__}: {exc}"
    return ValidationResult(
        output_path=str(output_path),
        passed=False,
        summary={"error": 1, "warning": 0, "info": 0},
        issues=[
            ValidationIssue(
                severity="error",
                code="format.failed",
                message=message,
                suggested_fix="Review mapping, input files, and debug artifacts.",
            )
        ],
        readiness=readiness_for_failure(message),
    )


def _check(name: str, status: str, message: str, suggested_fix: str | None = None) -> DoctorCheck:
    return DoctorCheck(name=name, status=status, message=message, suggested_fix=suggested_fix)


def _dependency_check(module_name: str, package_hint: str | None = None, required: bool = True) -> DoctorCheck:
    hint = package_hint or module_name
    if importlib.util.find_spec(module_name) is not None:
        return _check(f"dependency:{module_name}", "pass", f"{module_name} is available.")
    status = "error" if required else "warning"
    return _check(
        f"dependency:{module_name}",
        status,
        f"{module_name} is not installed.",
        f"Install with: uv sync --extra {'gui' if module_name == 'PySide6' else 'dev'} or pip install {hint}",
    )


def _docx_check(label: str, path: str | Path | None) -> DoctorCheck:
    if not path:
        return _check(label, "warning", f"{label} path was not provided.", "Pass the file path when checking a real run.")
    try:
        resolved = validate_docx_path(path)
    except Exception as exc:
        return _check(label, "error", str(exc), "Save the file as a valid .docx and run doctor again.")
    return _check(label, "pass", f"Valid .docx: {resolved}")


def _output_dir_check(path: str | Path | None) -> DoctorCheck:
    if not path:
        return _check("output_dir", "warning", "Output directory was not provided.", "Pass --out-dir for a full preflight.")
    out = Path(path).expanduser()
    target = out if out.exists() else out.parent
    if not target.exists():
        return _check("output_dir", "error", f"Parent directory does not exist: {target}", "Create the parent directory first.")
    if not os.access(target, os.W_OK):
        return _check("output_dir", "error", f"Directory is not writable: {target}", "Choose a writable work directory.")
    return _check("output_dir", "pass", f"Writable output location: {out}")


def _word_check() -> DoctorCheck:
    mac_word = Path("/Applications/Microsoft Word.app")
    if mac_word.exists():
        return _check("word", "pass", "Microsoft Word for Mac was found.")
    return _check(
        "word",
        "warning",
        "Microsoft Word was not found in /Applications.",
        "Final delivery still needs manual review in Microsoft Word, preferably Windows Word.",
    )


def doctor_check(
    template_path: str | Path | None = None,
    content_path: str | Path | None = None,
    out_dir: str | Path | None = None,
    require_gui: bool = False,
) -> DoctorResult:
    checks = [
        _check(
            "python",
            "pass" if sys.version_info >= (3, 11) else "error",
            f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "Use Python 3.11 or newer." if sys.version_info < (3, 11) else None,
        ),
        _dependency_check("lxml"),
        _dependency_check("pydantic"),
        _dependency_check("yaml", "PyYAML"),
        _dependency_check("docx", "python-docx"),
        _dependency_check("PySide6", required=require_gui),
        _docx_check("template", template_path),
        _docx_check("content", content_path),
        _output_dir_check(out_dir),
        _word_check(),
    ]
    summary = {
        "error": sum(1 for item in checks if item.status == "error"),
        "warning": sum(1 for item in checks if item.status == "warning"),
        "pass": sum(1 for item in checks if item.status == "pass"),
    }
    return DoctorResult(passed=summary["error"] == 0, summary=summary, checks=checks)
