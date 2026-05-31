from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Dict, Optional, Tuple

from models import ContentStructure, ParagraphBlock

from .docx_loader import list_parts, read_part, validate_docx_path
from .xml_utils import (
    NS,
    attr,
    extract_style_map,
    has_direct_paragraph_format,
    has_direct_run_format,
    paragraph_style_id,
    parse_xml,
    text_from_paragraph,
)


HEADING_3_RE = re.compile(r"^\d+(?:\.\d+){2,}\s+.+")
HEADING_2_RE = re.compile(r"^\d+\.\d+\s+.+")
HEADING_1_RE = re.compile(r"^(?:\d+|第[一二三四五六七八九十百千万0-9]+[章节])[\s、.．].+")
FIGURE_RE = re.compile(r"^(图|Figure)\s*\d+[-.\d]*")
TABLE_RE = re.compile(r"^(表|Table)\s*\d+[-.\d]*")
REFERENCE_RE = re.compile(r"^(\[\d+\]|\d+\.)\s*.+")


def _classify(text: str, paragraph, in_references: bool) -> Tuple[str, float, bool]:
    stripped = text.strip()
    if not stripped:
        return "body", 0.2, in_references
    compact = re.sub(r"\s+", " ", stripped)
    if compact in {"目录", "Contents", "Table of Contents"}:
        return "toc", 0.95, False
    if compact in {"参考文献", "References", "Bibliography"}:
        return "reference_heading", 0.95, True
    if compact.startswith(("摘要", "Abstract")):
        return "abstract", 0.9, False
    if compact.startswith(("关键词", "关键字", "Keywords", "Key words")):
        return "keywords", 0.95, False
    if compact.startswith(("附录", "Appendix")):
        return "appendix", 0.9, False
    if FIGURE_RE.match(compact):
        return "figure_caption", 0.92, in_references
    if TABLE_RE.match(compact):
        return "table_caption", 0.92, in_references
    if paragraph.xpath(".//m:oMath | .//m:oMathPara", namespaces=NS):
        return "equation", 0.9, in_references
    if in_references and REFERENCE_RE.match(compact):
        return "reference_item", 0.9, True
    if REFERENCE_RE.match(compact) and len(compact) > 20:
        return "reference_item", 0.7, in_references
    if HEADING_3_RE.match(compact):
        return "heading_3", 0.9, False
    if HEADING_2_RE.match(compact):
        return "heading_2", 0.9, False
    if HEADING_1_RE.match(compact):
        return "heading_1", 0.88, False
    return "body", 0.65, in_references


def _advanced_features(path: Path, document_root) -> Dict[str, object]:
    parts = list_parts(path)
    instr_text = " ".join(document_root.xpath(".//w:instrText/text()", namespaces=NS))
    return {
        "has_fields": bool(document_root.xpath(".//w:fldChar | .//w:instrText", namespaces=NS)),
        "has_toc_field": "TOC" in instr_text.upper(),
        "has_cross_reference_fields": "REF " in instr_text.upper() or "PAGEREF" in instr_text.upper(),
        "has_bookmarks": bool(document_root.xpath(".//w:bookmarkStart", namespaces=NS)),
        "has_omml_equations": bool(document_root.xpath(".//m:oMath | .//m:oMathPara", namespaces=NS)),
        "has_footnotes": "word/footnotes.xml" in parts,
        "has_endnotes": "word/endnotes.xml" in parts,
        "has_comments": "word/comments.xml" in parts,
        "media_part_count": len([name for name in parts if name.startswith("word/media/")]),
    }


def analyze_content(content_path: str | Path) -> ContentStructure:
    path = validate_docx_path(content_path)
    document_root = parse_xml(read_part(path, "word/document.xml"))
    styles_root = parse_xml(read_part(path, "word/styles.xml"))
    names = extract_style_map(styles_root)
    blocks = []
    counts: Counter = Counter()
    in_references = False
    for index, paragraph in enumerate(document_root.xpath(".//w:body//w:p", namespaces=NS)):
        text = text_from_paragraph(paragraph).strip()
        role, confidence, in_references = _classify(text, paragraph, in_references)
        style_id = paragraph_style_id(paragraph)
        style_name = names.get(style_id) if style_id else None
        block = ParagraphBlock(
            index=index,
            text_preview=text[:160],
            role=role,
            confidence=confidence,
            current_style_id=style_id,
            current_style_name=style_name,
            has_direct_paragraph_format=has_direct_paragraph_format(paragraph),
            has_direct_run_format=has_direct_run_format(paragraph),
        )
        if role in {"toc", "equation"}:
            block.notes.append("Detected advanced content; MVP reports this instead of rebuilding it.")
        blocks.append(block)
        counts[role] += 1
    return ContentStructure(
        source_path=str(path),
        blocks=blocks,
        role_counts=dict(counts),
        advanced_features=_advanced_features(path, document_root),
    )

