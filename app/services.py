from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Optional

from core.content_analyzer import analyze_content
from core.docx_loader import DocxError, validate_docx_path
from core.format_extractor import extract_format_profile
from core.formatter_engine import format_docx
from core.ooxml_security import raise_for_blocking_findings, scan_docx_security
from core.readiness import build_inspection_readiness, readiness_for_failure
from core.report_generator import write_delivery_checklist, write_inspection_report, write_validation_report
from core.style_mapper import build_style_mapping
from core.validator import validate_output
from models import ContentStructure, DoctorCheck, DoctorResult, FormatProfile, StyleMapping, ValidationIssue, ValidationResult
from models.io import load_model, write_model
from pydantic import ValidationError


def public_error_for(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, DocxError):
        return "input.docx", str(exc)
    if isinstance(exc, FileNotFoundError):
        return "input.file_missing", "输入文件或规则文件不存在。"
    if isinstance(exc, json.JSONDecodeError):
        return "mapping.invalid_json", "映射文件不是有效的 JSON。"
    if isinstance(exc, ValidationError):
        return "mapping.invalid_schema", "映射文件结构不符合要求。"
    return "format.failed", "处理失败，请检查输入文件、映射和调试报告。"


def public_error_message(exc: Exception) -> str:
    code, message = public_error_for(exc)
    return f"[{code}] {message}"


def _safe_output_label(path: str | Path) -> str:
    return Path(path).name or "output.docx"


def _relative_to(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_report_and_debug_paths(report_path: str | Path, debug_dir: Optional[str | Path]) -> None:
    report = Path(report_path).expanduser()
    if report.suffix.lower() != ".html":
        raise DocxError("报告路径必须是 .html 文件。")
    report_root = report.parent.resolve(strict=False)
    if debug_dir is None:
        return
    debug = Path(debug_dir).expanduser()
    if debug.exists() and debug.is_symlink():
        raise DocxError("调试目录不能是符号链接。")
    if not _relative_to(debug.resolve(strict=False), report_root):
        raise DocxError("调试目录必须位于报告目录内。")


def write_debug_error(debug_dir: Optional[str | Path], exc: Exception) -> None:
    if debug_dir is None:
        return
    root = Path(debug_dir).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    (root / "failure.txt").write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")


def inspect_documents(
    template_path: str | Path,
    content_path: str | Path,
    out_dir: str | Path,
    rules_path: Optional[str | Path] = None,
) -> tuple[FormatProfile, ContentStructure, StyleMapping]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    template_findings = scan_docx_security(template_path, "template")
    content_findings = scan_docx_security(content_path, "content")
    raise_for_blocking_findings([*template_findings, *content_findings])
    profile = extract_format_profile(template_path)
    structure = analyze_content(content_path)
    profile.security_findings = template_findings
    structure.security_findings = content_findings
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
    force: bool = False,
) -> ValidationResult:
    _validate_report_and_debug_paths(report_path, debug_dir)
    template_findings = scan_docx_security(template_path, "template")
    content_findings = scan_docx_security(content_path, "content")
    raise_for_blocking_findings([*template_findings, *content_findings])
    profile = extract_format_profile(template_path)
    structure = analyze_content(content_path)
    profile.security_findings = template_findings
    structure.security_findings = content_findings
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
        force=force,
    )
    result = validate_output(output, profile, structure, mapping)
    result.security_findings = [*template_findings, *content_findings]
    report = Path(report_path)
    report.parent.mkdir(parents=True, exist_ok=True)
    write_validation_report(report, result)
    write_model(report.parent / "validation_result.json", result)
    if result.readiness:
        write_model(report.parent / "delivery_checklist.json", result.readiness)
    write_delivery_checklist(report.parent / "delivery_checklist.html", result)
    return result


def validation_result_for_error(output_path: str | Path, exc: Exception) -> ValidationResult:
    code, message = public_error_for(exc)
    return ValidationResult(
        output_path=_safe_output_label(output_path),
        passed=False,
        summary={"error": 1, "warning": 0, "info": 0},
        issues=[
            ValidationIssue(
                severity="error",
                code=code,
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
        findings = scan_docx_security(resolved, label)
    except Exception as exc:
        return _check(label, "error", public_error_message(exc), "Save the file as a valid .docx and run doctor again.")
    blocking = [finding for finding in findings if finding.severity == "error"]
    warnings = [finding for finding in findings if finding.severity != "error"]
    if blocking:
        codes = ", ".join(sorted({finding.code for finding in blocking}))
        return _check(label, "error", f"Security check failed: {codes}", "Clean the document in Microsoft Word and retry.")
    if warnings:
        codes = ", ".join(sorted({finding.code for finding in warnings}))
        return _check(label, "warning", f"Security review needed: {codes}", "Review links and embedded objects before delivery.")
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
