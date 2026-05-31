from __future__ import annotations

from copy import deepcopy
from typing import Iterable, Optional

from lxml import etree

NS = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "m": "http://schemas.openxmlformats.org/officeDocument/2006/math",
    "ct": "http://schemas.openxmlformats.org/package/2006/content-types",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}


def qn(tag: str) -> str:
    prefix, local = tag.split(":", 1)
    return f"{{{NS[prefix]}}}{local}"


def parse_xml(data: bytes) -> etree._Element:
    return etree.fromstring(data)


def to_xml(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone="yes")


def attr(element: etree._Element, name: str) -> Optional[str]:
    return element.get(qn(name))


def find_child(parent: etree._Element, name: str) -> Optional[etree._Element]:
    return parent.find(name, namespaces=NS)


def ensure_child(parent: etree._Element, name: str, first: bool = False) -> etree._Element:
    child = find_child(parent, name)
    if child is not None:
        return child
    child = etree.Element(qn(name))
    if first:
        parent.insert(0, child)
    else:
        parent.append(child)
    return child


def extract_style_map(styles_root: etree._Element) -> dict[str, str]:
    """Extract a mapping from style ID to style name from word/styles.xml root."""
    result: dict[str, str] = {}
    for style in styles_root.findall("./w:style", namespaces=NS):
        style_id = attr(style, "w:styleId")
        name = style.find("./w:name", namespaces=NS)
        if style_id:
            val = attr(name, "w:val") if name is not None else None
            result[style_id] = val or style_id
    return result


def text_from_paragraph(paragraph: etree._Element) -> str:
    chunks = paragraph.xpath(".//w:t/text()", namespaces=NS)
    return "".join(chunks)


def paragraph_style_id(paragraph: etree._Element) -> Optional[str]:
    p_style = paragraph.find("./w:pPr/w:pStyle", namespaces=NS)
    return attr(p_style, "w:val") if p_style is not None else None


def set_paragraph_style_id(paragraph: etree._Element, style_id: str) -> None:
    p_pr = paragraph.find("./w:pPr", namespaces=NS)
    if p_pr is None:
        p_pr = etree.Element(qn("w:pPr"))
        paragraph.insert(0, p_pr)
    p_style = p_pr.find("./w:pStyle", namespaces=NS)
    if p_style is None:
        p_style = etree.Element(qn("w:pStyle"))
        p_pr.insert(0, p_style)
    p_style.set(qn("w:val"), style_id)


def has_direct_paragraph_format(paragraph: etree._Element) -> bool:
    p_pr = paragraph.find("./w:pPr", namespaces=NS)
    if p_pr is None:
        return False
    ignored = {qn("w:pStyle"), qn("w:numPr"), qn("w:rPr")}
    return any(child.tag not in ignored for child in p_pr)


def has_direct_run_format(paragraph: etree._Element) -> bool:
    return bool(paragraph.xpath("./w:r/w:rPr", namespaces=NS))


def conservative_cleanup_paragraph_format(paragraph: etree._Element) -> None:
    p_pr = paragraph.find("./w:pPr", namespaces=NS)
    if p_pr is None:
        return
    removable = {qn("w:jc"), qn("w:ind"), qn("w:spacing")}
    for child in list(p_pr):
        if child.tag in removable:
            p_pr.remove(child)


def copy_or_replace_child_by_attr(
    target_parent: etree._Element,
    source_children: Iterable[etree._Element],
    attr_name: str,
) -> None:
    existing = {child.get(qn(attr_name)): child for child in list(target_parent) if child.get(qn(attr_name))}
    for source_child in source_children:
        key = source_child.get(qn(attr_name))
        if not key:
            target_parent.append(deepcopy(source_child))
            continue
        old = existing.get(key)
        new_child = deepcopy(source_child)
        if old is not None:
            old.getparent().replace(old, new_child)
        else:
            target_parent.append(new_child)
        existing[key] = new_child

