from __future__ import annotations

import shutil
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Dict, Optional

from lxml import etree

from models import ContentStructure, FormatProfile, StyleMapping

from .docx_loader import (
    DocxError,
    assert_output_not_input,
    list_parts,
    read_part,
    validate_docx_can_open,
    validate_docx_path,
)
from .style_mapper import mapping_policy_issues, validate_mapping_consistency
from .xml_utils import (
    NS,
    conservative_cleanup_paragraph_format,
    copy_or_replace_child_by_attr,
    ensure_child,
    parse_xml,
    qn,
    set_paragraph_style_id,
    to_xml,
)


class MappingPolicyError(RuntimeError):
    pass


class MappingConsistencyError(RuntimeError):
    pass


def _merge_styles(template_styles: bytes, content_styles: bytes) -> bytes:
    template_root = parse_xml(template_styles)
    content_root = parse_xml(content_styles)
    copy_or_replace_child_by_attr(content_root, template_root.findall("./w:style", namespaces=NS), "w:styleId")
    return to_xml(content_root)


def _merge_numbering(template_numbering: Optional[bytes], content_numbering: Optional[bytes]) -> Optional[bytes]:
    if template_numbering is None and content_numbering is None:
        return None
    if template_numbering is None:
        return content_numbering
    if content_numbering is None:
        return template_numbering
    template_root = parse_xml(template_numbering)
    content_root = parse_xml(content_numbering)
    copy_or_replace_child_by_attr(content_root, template_root.findall("./w:abstractNum", namespaces=NS), "w:abstractNumId")
    copy_or_replace_child_by_attr(content_root, template_root.findall("./w:num", namespaces=NS), "w:numId")
    return to_xml(content_root)


def _copy_page_setup(template_doc: etree._Element, content_doc: etree._Element) -> None:
    template_sect = template_doc.xpath(".//w:sectPr", namespaces=NS)
    if not template_sect:
        return
    source = template_sect[-1]
    source_pg_sz = source.find("./w:pgSz", namespaces=NS)
    source_pg_mar = source.find("./w:pgMar", namespaces=NS)
    if source_pg_sz is None and source_pg_mar is None:
        return
    target_sections = content_doc.xpath(".//w:sectPr", namespaces=NS)
    if not target_sections:
        body = content_doc.find("./w:body", namespaces=NS)
        if body is None:
            return
        sect = etree.Element(qn("w:sectPr"))
        body.append(sect)
        target_sections = [sect]
    for target in target_sections:
        for tag, source_child in ((qn("w:pgSz"), source_pg_sz), (qn("w:pgMar"), source_pg_mar)):
            if source_child is None:
                continue
            existing = target.find(f"./{{{NS['w']}}}{tag.split('}', 1)[1]}")
            if existing is not None:
                target.remove(existing)
            target.insert(0, deepcopy(source_child))


def _apply_mapping(document_root: etree._Element, structure: ContentStructure, mapping: StyleMapping) -> None:
    entries = mapping.by_role()
    paragraphs = document_root.xpath(".//w:body//w:p", namespaces=NS)
    for block in structure.blocks:
        if block.index >= len(paragraphs):
            continue
        entry = entries.get(block.role)
        if not entry or not entry.style_id:
            continue
        paragraph = paragraphs[block.index]
        set_paragraph_style_id(paragraph, entry.style_id)
        conservative_cleanup_paragraph_format(paragraph)


def _preserve_debug(debug_dir: Optional[str | Path], files: Dict[str, bytes | str]) -> None:
    if not debug_dir:
        return
    root = Path(debug_dir)
    root.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, bytes):
            target.write_bytes(data)
        else:
            target.write_text(data, encoding="utf-8")


def _merge_parts(
    template: Path,
    content: Path,
    document_xml: bytes,
    styles_xml: bytes,
    numbering_xml: Optional[bytes],
    temp_output: Path,
) -> None:
    with zipfile.ZipFile(content, "r") as source, zipfile.ZipFile(temp_output, "w", zipfile.ZIP_DEFLATED) as target:
        names = set(source.namelist())
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "word/document.xml":
                data = document_xml
            elif item.filename == "word/styles.xml":
                data = styles_xml
            elif item.filename == "word/numbering.xml" and numbering_xml is not None:
                data = numbering_xml
            target.writestr(item, data)
        if numbering_xml is not None and "word/numbering.xml" not in names:
            target.writestr("word/numbering.xml", numbering_xml)


def format_docx(
    template_path: str | Path,
    content_path: str | Path,
    output_path: str | Path,
    structure: ContentStructure,
    mapping: StyleMapping,
    profile: Optional[FormatProfile] = None,
    strict: bool = False,
    debug_dir: Optional[str | Path] = None,
) -> Path:
    template = validate_docx_path(template_path)
    content = validate_docx_path(content_path)
    output = Path(output_path)
    assert_output_not_input(output, [template, content])

    policy_issues = mapping_policy_issues(mapping, strict=strict)
    if policy_issues:
        missing = [entry for entry in policy_issues if not entry.style_id]
        low_conf = [entry for entry in policy_issues if entry.style_id]
        if missing or (strict and low_conf):
            roles = ", ".join(entry.role for entry in policy_issues)
            raise MappingPolicyError(f"Mapping policy blocked formatting for roles: {roles}")

    if profile:
        consistency_errors = validate_mapping_consistency(profile, mapping)
        if consistency_errors:
            raise MappingConsistencyError("; ".join(consistency_errors))

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="thesis_formatter_") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        temp_output = temp_dir / f"{output.stem}.tmp.docx"
        try:
            template_doc = parse_xml(read_part(template, "word/document.xml"))
            content_doc = parse_xml(read_part(content, "word/document.xml"))

            styles_xml = _merge_styles(read_part(template, "word/styles.xml"), read_part(content, "word/styles.xml"))

            content_parts = set(list_parts(content))
            template_parts = set(list_parts(template))

            numbering_xml = None
            if "word/numbering.xml" in template_parts or "word/numbering.xml" in content_parts:
                numbering_xml = _merge_numbering(
                    read_part(template, "word/numbering.xml") if "word/numbering.xml" in template_parts else None,
                    read_part(content, "word/numbering.xml") if "word/numbering.xml" in content_parts else None,
                )

            _copy_page_setup(template_doc, content_doc)
            _apply_mapping(content_doc, structure, mapping)
            document_xml = to_xml(content_doc)

            _merge_parts(template, content, document_xml, styles_xml, numbering_xml, temp_output)

            validate_docx_can_open(temp_output)
            _preserve_debug(
                debug_dir,
                {
                    "word/document.xml": document_xml,
                    "word/styles.xml": styles_xml,
                    "word/numbering.xml": numbering_xml or b"",
                    "debug.txt": "Generated successfully before final move.\n",
                },
            )
            shutil.move(str(temp_output), str(output))
            return output
        except Exception as exc:
            _preserve_debug(
                debug_dir,
                {
                    "failure.txt": f"{type(exc).__name__}: {exc}\n",
                },
            )
            if temp_output.exists() and debug_dir:
                shutil.copy2(temp_output, Path(debug_dir) / temp_output.name)
            raise
