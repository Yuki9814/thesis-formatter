from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional

from lxml import etree

from models import FormatProfile, RFonts, SectionProfile, StyleProfile, TemplateQuality
from models.schema import ParagraphProperties

from .docx_loader import list_parts, read_part, validate_docx_path
from .xml_utils import NS, attr, has_direct_paragraph_format, has_direct_run_format, parse_xml, text_from_paragraph


def _int_attr(element: Optional[etree._Element], name: str) -> Optional[int]:
    if element is None:
        return None
    value = attr(element, name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _rfonts_from(r_pr: Optional[etree._Element]) -> RFonts:
    if r_pr is None:
        return RFonts()
    r_fonts = r_pr.find("./w:rFonts", namespaces=NS)
    if r_fonts is None:
        return RFonts()
    return RFonts(
        ascii=attr(r_fonts, "w:ascii"),
        hAnsi=attr(r_fonts, "w:hAnsi"),
        eastAsia=attr(r_fonts, "w:eastAsia"),
        cs=attr(r_fonts, "w:cs"),
    )


def _properties_from_style(style: etree._Element) -> ParagraphProperties:
    p_pr = style.find("./w:pPr", namespaces=NS)
    r_pr = style.find("./w:rPr", namespaces=NS)
    ind = p_pr.find("./w:ind", namespaces=NS) if p_pr is not None else None
    spacing = p_pr.find("./w:spacing", namespaces=NS) if p_pr is not None else None
    jc = p_pr.find("./w:jc", namespaces=NS) if p_pr is not None else None
    size = r_pr.find("./w:sz", namespaces=NS) if r_pr is not None else None
    return ParagraphProperties(
        alignment=attr(jc, "w:val") if jc is not None else None,
        first_line_indent_twips=_int_attr(ind, "w:firstLine"),
        left_indent_twips=_int_attr(ind, "w:left"),
        right_indent_twips=_int_attr(ind, "w:right"),
        space_before_twips=_int_attr(spacing, "w:before"),
        space_after_twips=_int_attr(spacing, "w:after"),
        line_spacing=attr(spacing, "w:line") if spacing is not None else None,
        rfonts=_rfonts_from(r_pr),
        size_half_points=_int_attr(size, "w:val"),
        bold=r_pr.find("./w:b", namespaces=NS) is not None if r_pr is not None else None,
        italic=r_pr.find("./w:i", namespaces=NS) is not None if r_pr is not None else None,
    )


def _extract_styles(styles_xml: bytes, style_usage: Counter, samples: Dict[str, List[str]]) -> List[StyleProfile]:
    styles_root = parse_xml(styles_xml)
    styles: List[StyleProfile] = []
    for style in styles_root.findall("./w:style", namespaces=NS):
        style_id = attr(style, "w:styleId")
        if not style_id:
            continue
        name = style.find("./w:name", namespaces=NS)
        based_on = style.find("./w:basedOn", namespaces=NS)
        styles.append(
            StyleProfile(
                style_id=style_id,
                style_name=attr(name, "w:val") or style_id,
                style_type=attr(style, "w:type") or "unknown",
                based_on=attr(based_on, "w:val") if based_on is not None else None,
                is_default=attr(style, "w:default") == "1",
                paragraph_count=int(style_usage.get(style_id, 0)),
                sample_texts=samples.get(style_id, [])[:3],
                properties=_properties_from_style(style),
            )
        )
    styles.sort(key=lambda item: (item.style_type, item.style_name.lower()))
    return styles


def _extract_sections(document_root: etree._Element) -> List[SectionProfile]:
    sections: List[SectionProfile] = []
    for index, sect_pr in enumerate(document_root.xpath(".//w:sectPr", namespaces=NS)):
        pg_sz = sect_pr.find("./w:pgSz", namespaces=NS)
        pg_mar = sect_pr.find("./w:pgMar", namespaces=NS)
        sections.append(
            SectionProfile(
                index=index,
                page_width_twips=_int_attr(pg_sz, "w:w"),
                page_height_twips=_int_attr(pg_sz, "w:h"),
                orientation=attr(pg_sz, "w:orient") if pg_sz is not None else None,
                margin_top_twips=_int_attr(pg_mar, "w:top"),
                margin_bottom_twips=_int_attr(pg_mar, "w:bottom"),
                margin_left_twips=_int_attr(pg_mar, "w:left"),
                margin_right_twips=_int_attr(pg_mar, "w:right"),
                header_twips=_int_attr(pg_mar, "w:header"),
                footer_twips=_int_attr(pg_mar, "w:footer"),
                gutter_twips=_int_attr(pg_mar, "w:gutter"),
            )
        )
    return sections


def _advanced_features(path: Path, document_root: etree._Element) -> Dict[str, object]:
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
        "header_footer_part_count": len(
            [name for name in parts if name.startswith("word/header") or name.startswith("word/footer")]
        ),
    }


def _template_quality(total: int, styled: int, direct_p: int, direct_r: int) -> TemplateQuality:
    direct_ratio = ((direct_p + direct_r) / max(total * 2, 1)) if total else 0.0
    warnings: List[str] = []
    reliable = True
    if total and styled / total < 0.55:
        reliable = False
        warnings.append("Most paragraphs do not use reusable paragraph styles.")
    if direct_ratio > 0.45:
        reliable = False
        warnings.append("The reference contains heavy direct formatting and may be unreliable as a style source.")
    return TemplateQuality(
        total_paragraphs=total,
        styled_paragraphs=styled,
        direct_paragraph_format_count=direct_p,
        direct_run_format_count=direct_r,
        direct_format_ratio=round(direct_ratio, 3),
        reliable_style_source=reliable,
        warnings=warnings,
    )


def extract_format_profile(template_path: str | Path) -> FormatProfile:
    path = validate_docx_path(template_path)
    document_root = parse_xml(read_part(path, "word/document.xml"))
    style_usage: Counter = Counter()
    samples: Dict[str, List[str]] = defaultdict(list)
    total = 0
    styled = 0
    direct_p = 0
    direct_r = 0
    for paragraph in document_root.xpath(".//w:body//w:p", namespaces=NS):
        total += 1
        style_id = None
        p_style = paragraph.find("./w:pPr/w:pStyle", namespaces=NS)
        if p_style is not None:
            style_id = attr(p_style, "w:val")
        if style_id:
            styled += 1
            style_usage[style_id] += 1
            text = text_from_paragraph(paragraph).strip()
            if text and len(samples[style_id]) < 3:
                samples[style_id].append(text[:120])
        if has_direct_paragraph_format(paragraph):
            direct_p += 1
        if has_direct_run_format(paragraph):
            direct_r += 1

    styles_xml = read_part(path, "word/styles.xml")
    numbering_ids: List[str] = []
    if "word/numbering.xml" in list_parts(path):
        numbering_root = parse_xml(read_part(path, "word/numbering.xml"))
        numbering_ids = [
            attr(node, "w:abstractNumId") or attr(node, "w:numId") or ""
            for node in numbering_root.xpath("./w:abstractNum | ./w:num", namespaces=NS)
        ]
        numbering_ids = [item for item in numbering_ids if item]

    parts = list_parts(path)
    return FormatProfile(
        source_path=str(path),
        styles=_extract_styles(styles_xml, style_usage, samples),
        sections=_extract_sections(document_root),
        style_usage=dict(style_usage),
        numbering_ids=numbering_ids,
        header_footer_parts=[
            name for name in parts if name.startswith("word/header") or name.startswith("word/footer")
        ],
        advanced_features=_advanced_features(path, document_root),
        template_quality=_template_quality(total, styled, direct_p, direct_r),
    )

