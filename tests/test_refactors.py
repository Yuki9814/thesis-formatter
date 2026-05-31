from __future__ import annotations

from pathlib import Path

import pytest

from app.services import format_documents, inspect_documents
from core.formatter_engine import MappingConsistencyError
from models import StyleMapping
from models.io import load_model, write_model


def test_format_blocks_invalid_style_id(simple_template: Path, simple_content: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "workdir"
    inspect_documents(simple_template, simple_content, out_dir)
    mapping_path = out_dir / "mapping.generated.json"
    mapping = load_model(mapping_path, StyleMapping)

    # Inject a non-existent style_id
    for entry in mapping.entries:
        if entry.role == "heading_1":
            entry.style_id = "NonExistentStyle"
            break

    invalid_mapping_path = out_dir / "mapping.invalid.json"
    write_model(invalid_mapping_path, mapping)

    output = tmp_path / "failed.docx"
    report = out_dir / "failed_report.html"

    with pytest.raises(MappingConsistencyError) as excinfo:
        format_documents(
            simple_template,
            simple_content,
            invalid_mapping_path,
            output,
            report,
        )
    assert "maps to missing style ID 'NonExistentStyle'" in str(excinfo.value)


def test_mapping_entry_validation() -> None:
    from models import MappingEntry
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MappingEntry(role="body", confidence=1.5)
    with pytest.raises(ValidationError):
        MappingEntry(role="", confidence=0.5)


def test_extract_style_map_fallback_to_id_when_name_missing() -> None:
    """Regression: extract_style_map must fallback to styleId when <w:name> is absent or has empty val.

    This covers the safe fallback path (previously AttributeError on missing w:name).
    Tiny, lxml-only, no docx fixtures or side effects.
    """
    from lxml import etree

    from core.xml_utils import extract_style_map

    styles_xml = b"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:style w:styleId="Heading1" w:type="paragraph">
    <w:name w:val="Heading 1"/>
  </w:style>
  <w:style w:styleId="NoNameFallback" w:type="paragraph"/>
  <w:style w:styleId="EmptyValFallback" w:type="paragraph">
    <w:name w:val=""/>
  </w:style>
</w:styles>
"""
    root = etree.fromstring(styles_xml)
    mapping = extract_style_map(root)
    assert mapping["Heading1"] == "Heading 1"
    assert mapping["NoNameFallback"] == "NoNameFallback"  # key regression case
    assert mapping["EmptyValFallback"] == "EmptyValFallback"
    assert len(mapping) == 3


def test_copy_or_replace_child_by_attr() -> None:
    from lxml import etree

    from core.xml_utils import copy_or_replace_child_by_attr

    target = etree.fromstring(
        '<root xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:style w:styleId="S1" val="old"/>'
        '<w:style w:styleId="S2" val="keep"/>'
        "</root>"
    )
    sources = [
        etree.fromstring('<w:style xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:styleId="S1" val="new"/>'),
        etree.fromstring('<w:style xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:styleId="S3" val="added"/>'),
        # Edge case: duplicate key in source
        etree.fromstring('<w:style xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" w:styleId="S1" val="final"/>'),
    ]

    copy_or_replace_child_by_attr(target, sources, "w:styleId")

    styles = target.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}style")
    results = {s.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}styleId"): s.get("val") for s in styles}

    assert results["S1"] == "final"
    assert results["S2"] == "keep"
    assert results["S3"] == "added"
    assert len(styles) == 3
