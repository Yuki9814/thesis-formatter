from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

import pytest

from app.services import format_documents, inspect_documents
from core.docx_loader import DocxError, DocxPackagePolicy, validate_docx_package
from core.ooxml_security import scan_docx_security
from core.xml_utils import parse_xml
from models import ReadinessResult, StyleMapping
from models.io import load_model


def _minimal_docx(path: Path, additions: dict[str, bytes] | None = None) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr(
            "[Content_Types].xml",
            b'<?xml version="1.0"?>'
            b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            b'<Default Extension="xml" ContentType="application/xml"/></Types>',
        )
        package.writestr(
            "word/document.xml",
            b'<?xml version="1.0"?>'
            b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>',
        )
        for name, data in (additions or {}).items():
            package.writestr(name, data)
    return path


def _copy_docx(src: Path, dst: Path, additions: dict[str, bytes] | None = None) -> Path:
    shutil.copy2(src, dst)
    tmp = dst.with_suffix(".rewrite.docx")
    additions = additions or {}
    with zipfile.ZipFile(dst, "r") as original, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as rewritten:
        existing = set(original.namelist())
        for item in original.infolist():
            rewritten.writestr(item, additions.get(item.filename, original.read(item.filename)))
        for name, data in additions.items():
            if name not in existing:
                rewritten.writestr(name, data)
    shutil.move(tmp, dst)
    return dst


def test_docx_package_rejects_resource_and_path_risks(tmp_path: Path) -> None:
    policy = DocxPackagePolicy(
        max_file_bytes=1024 * 1024,
        max_parts=4,
        max_part_uncompressed_bytes=512,
        max_total_uncompressed_bytes=1024,
        max_compression_ratio=2,
        compression_ratio_min_bytes=128,
    )
    too_many = _minimal_docx(
        tmp_path / "too_many.docx",
        {"a.xml": b"x", "b.xml": b"x", "c.xml": b"x"},
    )
    with pytest.raises(DocxError, match="过多"):
        validate_docx_package(too_many, policy)

    too_large = _minimal_docx(tmp_path / "too_large.docx", {"word/large.xml": b"x" * 600})
    with pytest.raises(DocxError, match="过大"):
        validate_docx_package(too_large, policy)

    zip_slip = _minimal_docx(tmp_path / "zip_slip.docx", {"../evil.xml": b"x"})
    with pytest.raises(DocxError, match="不安全"):
        validate_docx_package(zip_slip, policy)

    bomb = _minimal_docx(tmp_path / "bomb.docx", {"word/bomb.xml": b"0" * 200})
    with pytest.raises(DocxError, match="压缩比"):
        validate_docx_package(bomb, policy)


def test_parse_xml_rejects_doctype_and_entities() -> None:
    with pytest.raises(DocxError, match="XML"):
        parse_xml(b'<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>')


def test_ooxml_security_blocks_macro_and_warns_for_http_hyperlink(tmp_path: Path) -> None:
    macro_docx = _minimal_docx(tmp_path / "macro.docx", {"word/vbaProject.bin": b"macro"})
    findings = scan_docx_security(macro_docx, "content")
    assert any(item.severity == "error" and item.code == "security.macro" for item in findings)

    rels = b"""<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
    Target="https://example.com" TargetMode="External"/>
</Relationships>
"""
    link_docx = _minimal_docx(tmp_path / "link.docx", {"word/_rels/document.xml.rels": rels})
    link_findings = scan_docx_security(link_docx, "content")
    assert any(item.severity == "warning" and item.code == "security.external_hyperlink" for item in link_findings)


def test_security_findings_enter_inspection_readiness(simple_template: Path, simple_content: Path, tmp_path: Path) -> None:
    rels = b"""<?xml version="1.0"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
    Target="https://example.com" TargetMode="External"/>
</Relationships>
"""
    content = _copy_docx(simple_content, tmp_path / "content_with_link.docx", {"word/_rels/document.xml.rels": rels})
    out_dir = tmp_path / "inspect"
    _, structure, _ = inspect_documents(simple_template, content, out_dir)
    readiness = load_model(out_dir / "readiness_result.json", ReadinessResult)
    assert any(item.code == "security.external_hyperlink" for item in structure.security_findings)
    assert readiness.status == "需复核"
    assert any("security.external_hyperlink" in item for item in readiness.manual_review_items)


def test_format_output_requires_force_for_existing_file(simple_template: Path, simple_content: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "workdir"
    inspect_documents(simple_template, simple_content, out_dir)
    mapping_path = out_dir / "mapping.generated.json"
    output = tmp_path / "formatted.docx"
    report = out_dir / "validation_report.html"
    format_documents(simple_template, simple_content, mapping_path, output, report)

    with pytest.raises(DocxError, match="--force"):
        format_documents(simple_template, simple_content, mapping_path, output, report)

    result = format_documents(simple_template, simple_content, mapping_path, output, report, force=True)
    assert result.output_path == str(output)

    mapping = load_model(mapping_path, StyleMapping)
    assert mapping.entries
