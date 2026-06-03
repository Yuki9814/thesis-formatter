from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from app.services import format_documents, inspect_documents
from core.content_analyzer import analyze_content
from core.format_extractor import extract_format_profile
from core.formatter_engine import MappingPolicyError
from core.docx_loader import DocxError, assert_output_not_input, read_part, validate_docx_path
from models import ReadinessResult, StyleMapping
from models.io import load_model, write_model


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_inspect_outputs_without_modifying_inputs(simple_template: Path, simple_content: Path, tmp_path: Path) -> None:
    before = _sha(simple_content)
    out_dir = tmp_path / "workdir"
    profile, structure, mapping = inspect_documents(simple_template, simple_content, out_dir)
    assert before == _sha(simple_content)
    assert (out_dir / "format_profile.json").exists()
    assert (out_dir / "content_structure.json").exists()
    assert (out_dir / "mapping.generated.json").exists()
    assert (out_dir / "inspection_report.html").exists()
    assert any(style.style_id and style.style_name for style in profile.styles)
    assert structure.role_counts["heading_1"] == 1
    assert any(entry.role == "heading_1" and entry.style_id for entry in mapping.entries)
    readiness = load_model(out_dir / "readiness_result.json", ReadinessResult)
    assert readiness.score >= 0
    assert readiness.status in {"可交付", "需复核", "不建议交付"}
    assert any(entry.sample_texts for entry in mapping.entries)
    assert any(entry.candidate_styles for entry in mapping.entries)


def test_format_uses_editable_mapping(simple_template: Path, simple_content: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "workdir"
    inspect_documents(simple_template, simple_content, out_dir)
    mapping_path = out_dir / "mapping.generated.json"
    mapping = load_model(mapping_path, StyleMapping)
    for entry in mapping.entries:
        if entry.role == "body":
            entry.warning = "edited by test"
    edited = out_dir / "mapping.edited.json"
    write_model(edited, mapping)
    output = tmp_path / "formatted.docx"
    report = out_dir / "validation_report.html"
    result = format_documents(simple_template, simple_content, edited, output, report)
    assert output.exists()
    assert report.exists()
    assert (out_dir / "validation_result.json").exists()
    assert (out_dir / "delivery_checklist.json").exists()
    assert (out_dir / "delivery_checklist.html").exists()
    assert result.summary["error"] == 0
    assert result.readiness is not None


def test_strict_blocks_low_confidence_mapping(simple_template: Path, simple_content: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "workdir"
    inspect_documents(simple_template, simple_content, out_dir)
    mapping = load_model(out_dir / "mapping.generated.json", StyleMapping)
    for entry in mapping.entries:
        if entry.required and entry.style_id:
            entry.confidence = 0.1
            break
    mapping_path = out_dir / "mapping.low.json"
    write_model(mapping_path, mapping)
    with pytest.raises(MappingPolicyError):
        format_documents(
            simple_template,
            simple_content,
            mapping_path,
            tmp_path / "blocked.docx",
            out_dir / "blocked.html",
            strict=True,
        )


def test_template_quality_warns_for_direct_format_reference(bad_reference: Path) -> None:
    profile = extract_format_profile(bad_reference)
    assert not profile.template_quality.reliable_style_source
    assert profile.template_quality.warnings


def test_advanced_content_detection(advanced_content: Path) -> None:
    structure = analyze_content(advanced_content)
    features = structure.advanced_features
    assert features["has_toc_field"]
    assert features["has_bookmarks"]
    assert features["has_omml_equations"]
    assert features["has_footnotes"]
    assert features["has_endnotes"]
    assert features["media_part_count"] >= 1


def test_chinese_thesis_role_detection(tmp_path: Path) -> None:
    from docx import Document

    path = tmp_path / "chinese_roles.docx"
    doc = Document()
    for text in [
        "目 录",
        "摘要",
        "关键词：格式；论文",
        "第1章 绪论",
        "一、研究背景",
        "（一）理论基础",
        "1.1.1 细分问题",
        "图1-1 系统流程图",
        "表一 样本表",
        "参考文献：",
        "[1] Zhang S. A reference item.",
        "附录A 调查问卷",
    ]:
        doc.add_paragraph(text)
    doc.save(path)

    structure = analyze_content(path)
    assert structure.blocks[0].role == "toc"
    assert structure.role_counts["abstract"] == 1
    assert structure.role_counts["keywords"] == 1
    assert structure.role_counts["heading_1"] >= 2
    assert structure.role_counts["heading_2"] >= 1
    assert structure.role_counts["heading_3"] == 1
    assert structure.role_counts["figure_caption"] == 1
    assert structure.role_counts["table_caption"] == 1
    assert structure.role_counts["reference_heading"] == 1
    assert structure.role_counts["reference_item"] == 1
    assert structure.role_counts["appendix"] == 1


def test_cli_inspect_and_format(simple_template: Path, table_content: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "cli_workdir"
    inspect_cmd = [
        sys.executable,
        "-m",
        "app.main",
        "inspect",
        "--template",
        str(simple_template),
        "--content",
        str(table_content),
        "--out-dir",
        str(out_dir),
    ]
    inspect_result = subprocess.run(inspect_cmd, cwd=Path.cwd(), text=True, capture_output=True)
    assert inspect_result.returncode == 0, inspect_result.stderr
    format_cmd = [
        sys.executable,
        "-m",
        "app.main",
        "format",
        "--template",
        str(simple_template),
        "--content",
        str(table_content),
        "--mapping",
        str(out_dir / "mapping.generated.json"),
        "--out",
        str(tmp_path / "cli_output.docx"),
        "--report",
        str(out_dir / "validation_report.html"),
        "--debug-dir",
        str(out_dir / "debug"),
    ]
    format_result = subprocess.run(format_cmd, cwd=Path.cwd(), text=True, capture_output=True)
    assert format_result.returncode in {0, 1}, format_result.stderr
    assert (tmp_path / "cli_output.docx").exists()
    assert (out_dir / "debug" / "word" / "document.xml").exists()


def test_cli_exit_code_for_invalid_input(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.main",
            "inspect",
            "--template",
            str(tmp_path / "missing.docx"),
            "--content",
            str(tmp_path / "missing2.docx"),
            "--out-dir",
            str(tmp_path / "workdir"),
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2


def test_cli_doctor_reports_bad_inputs(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.main",
            "doctor",
            "--template",
            str(tmp_path / "missing.docx"),
            "--content",
            str(tmp_path / "missing2.docx"),
            "--out-dir",
            str(tmp_path),
            "--json",
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    data = json.loads(result.stdout)
    assert data["passed"] is False
    assert data["summary"]["error"] >= 2


def test_cli_exit_code_for_strict_mapping_failure(simple_template: Path, simple_content: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "strict_workdir"
    inspect_documents(simple_template, simple_content, out_dir)
    mapping = load_model(out_dir / "mapping.generated.json", StyleMapping)
    for entry in mapping.entries:
        if entry.required and entry.style_id:
            entry.confidence = 0.1
            break
    mapping_path = out_dir / "mapping.low.json"
    write_model(mapping_path, mapping)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.main",
            "format",
            "--template",
            str(simple_template),
            "--content",
            str(simple_content),
            "--mapping",
            str(mapping_path),
            "--out",
            str(tmp_path / "strict_output.docx"),
            "--report",
            str(out_dir / "validation_report.html"),
            "--strict",
        ],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
    )
    assert result.returncode == 1
    assert (out_dir / "validation_result.json").exists()


def test_documented_smoke_script_runs(tmp_path: Path) -> None:
    script = Path.cwd() / "scripts" / "smoke_test.py"
    result = subprocess.run([sys.executable, str(script)], cwd=tmp_path, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "examples" / "template_basic.docx").exists()
    assert (tmp_path / "examples" / "content_basic.docx").exists()
    assert (tmp_path / "workdir" / "output.docx").exists()
    assert (tmp_path / "workdir" / "validation_report.html").exists()


def test_gui_imports_when_pyside_is_available() -> None:
    pytest.importorskip("PySide6")
    import gui.main_window  # noqa: F401


def test_docx_loader_error_cases(tmp_path: Path) -> None:
    """Cover DocxError paths for invalid inputs (CLI edge + loader robustness)."""
    # Non-existent file
    missing = tmp_path / "nope.docx"
    with pytest.raises(DocxError) as exc:
        validate_docx_path(missing)
    assert "不存在" in str(exc.value)

    # Wrong suffix
    bad_suffix = tmp_path / "fake.txt"
    bad_suffix.write_text("not a docx")
    with pytest.raises(DocxError) as exc:
        validate_docx_path(bad_suffix)
    assert ".docx" in str(exc.value)

    # Not a zip (but .docx name)
    not_zip = tmp_path / "notzip.docx"
    not_zip.write_bytes(b"PK not really zip")
    with pytest.raises(DocxError) as exc:
        validate_docx_path(not_zip)
    assert "有效" in str(exc.value)

    # Valid zip but missing required parts
    bad_pkg = tmp_path / "badpkg.docx"
    with zipfile.ZipFile(bad_pkg, "w") as zf:
        zf.writestr("word/document.xml", b"<xml/>")  # missing [Content_Types]
    with pytest.raises(DocxError) as exc:
        validate_docx_path(bad_pkg)
    assert "必要" in str(exc.value)

    # Valid package by minimal loader rules, but missing optional parts callers may request.
    no_styles = tmp_path / "no_styles.docx"
    with zipfile.ZipFile(no_styles, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            b'<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            b'<Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        zf.writestr(
            "word/document.xml",
            b'<?xml version="1.0"?>'
            b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>',
        )
    validate_docx_path(no_styles)
    with pytest.raises(DocxError) as exc:
        read_part(no_styles, "word/styles.xml")
    assert "Missing docx part" in str(exc.value)
    assert "styles.xml" in str(exc.value)

    # Output overwrite guard
    out = tmp_path / "out.docx"
    out.write_bytes(b"")
    with pytest.raises(DocxError) as exc:
        assert_output_not_input(out, [out])
    assert "must not overwrite an input file" in str(exc.value)


def test_cli_format_bad_mapping_json(tmp_path: Path, simple_template: Path, simple_content: Path) -> None:
    """CLI edge: format with bad mapping (JSON decode + pydantic ValidationError) produces exit 2 and failure report."""
    out_dir = tmp_path / "badmap_workdir"
    out_dir.mkdir()
    inspect_documents(simple_template, simple_content, out_dir)
    output = tmp_path / "should_not_exist.docx"
    report = out_dir / "badmap_report.html"
    result_json = out_dir / "validation_result.json"

    # Case 1: malformed JSON
    bad_json = out_dir / "bad.json"
    bad_json.write_text("{ not valid json ", encoding="utf-8")
    res = subprocess.run(
        [
            sys.executable, "-m", "app.main", "format",
            "--template", str(simple_template),
            "--content", str(simple_content),
            "--mapping", str(bad_json),
            "--out", str(output),
            "--report", str(report),
        ],
        cwd=Path.cwd(), text=True, capture_output=True,
    )
    assert res.returncode == 2
    assert report.exists(), "Failure report must be written on JSON error"
    assert result_json.exists()
    data = json.loads(result_json.read_text(encoding="utf-8"))
    assert data["passed"] is False
    assert any(iss.get("code") == "mapping.invalid_json" for iss in data.get("issues", []))
    assert "JSONDecodeError" not in report.read_text(encoding="utf-8")

    # Case 2: valid JSON but fails Pydantic schema (e.g. missing required 'role' or bad type)
    bad_schema = out_dir / "bad_schema.json"
    bad_schema.write_text(json.dumps({"generated_at": "2020-01-01", "entries": [{"style_id": "foo"}]}), encoding="utf-8")
    res2 = subprocess.run(
        [
            sys.executable, "-m", "app.main", "format",
            "--template", str(simple_template),
            "--content", str(simple_content),
            "--mapping", str(bad_schema),
            "--out", str(output),
            "--report", str(report),
        ],
        cwd=Path.cwd(), text=True, capture_output=True,
    )
    assert res2.returncode == 2
    assert report.exists()
    data2 = json.loads(result_json.read_text(encoding="utf-8"))
    assert data2["passed"] is False


def test_cli_format_error_with_missing_report_parent_dir(tmp_path: Path, simple_template: Path, simple_content: Path) -> None:
    inspect_dir = tmp_path / "inspect_workdir"
    inspect_dir.mkdir()
    inspect_documents(simple_template, simple_content, inspect_dir)

    bad_map = inspect_dir / "bad.json"
    bad_map.write_text("{ not valid json ", encoding="utf-8")

    report_parent = tmp_path / "nonexistent_report_dir"
    report = report_parent / "failure_report.html"
    result_json = report_parent / "validation_result.json"
    output = tmp_path / "should_not_be_written.docx"

    res = subprocess.run(
        [
            sys.executable, "-m", "app.main", "format",
            "--template", str(simple_template),
            "--content", str(simple_content),
            "--mapping", str(bad_map),
            "--out", str(output),
            "--report", str(report),
        ],
        cwd=Path.cwd(), text=True, capture_output=True,
    )

    assert res.returncode == 2
    assert report.exists()
    assert result_json.exists()
    data = json.loads(result_json.read_text(encoding="utf-8"))
    assert data["passed"] is False
    assert any(iss.get("code") == "mapping.invalid_json" for iss in data.get("issues", []))
    assert "JSONDecodeError" not in report.read_text(encoding="utf-8")


def test_format_preserves_complex_content_parts(simple_template: Path, advanced_content: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "advanced_workdir"
    inspect_documents(simple_template, advanced_content, out_dir)
    output = tmp_path / "advanced_output.docx"
    result = format_documents(
        simple_template,
        advanced_content,
        out_dir / "mapping.generated.json",
        output,
        out_dir / "validation_report.html",
    )
    assert output.exists()
    parts = set(zipfile.ZipFile(output).namelist())
    assert "word/footnotes.xml" in parts
    assert "word/endnotes.xml" in parts
    assert any(name.startswith("word/media/") for name in parts)
    assert result.readiness is not None
    assert any("目录" in item or "TOC" in item for item in result.readiness.manual_review_items)
