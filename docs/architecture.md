# Architecture

## Data Flow

```text
template/reference.docx ─┐
                         ├─ inspect ─ format_profile.json
content.docx ────────────┘           ├─ content_structure.json
                                     ├─ mapping.generated.json
                                     ├─ readiness_result.json
                                     └─ inspection_report.html

mapping.generated.json + content.docx + template/reference.docx
  └─ format ─ output.docx
             ├─ validation_result.json
             ├─ delivery_checklist.json
             ├─ delivery_checklist.html
             └─ validation_report.html
```

## Module Responsibilities

- `core/docx_loader.py`: validates `.docx` packages and reads Word package parts.
- `core/format_extractor.py`: extracts styles, page setup, rFonts, section metadata, template quality, and advanced feature indicators from the template/reference document.
- `core/content_analyzer.py`: classifies paragraphs into roles such as `heading_1`, `body`, `figure_caption`, and `reference_item` using deterministic rules.
- `core/style_mapper.py`: builds editable role-to-style mappings from rules and style heuristics.
- `core/readiness.py`: turns template quality, mapping confidence, advanced content, and validation issues into delivery status, score, risk, blockers, review items, and next actions.
- `core/formatter_engine.py`: copies the content document, imports/merges template styles, applies mapped `style_id` values, applies safe page setup, and writes a validated temporary `.docx` before final output.
- `core/validator.py`: validates the generated document against the extracted profile and mapping.
- `core/report_generator.py`: writes human-readable inspection and validation HTML reports.
- `gui/`: PySide6 interface around the same service layer used by the CLI.

## Why Deterministic Formatting

The MVP avoids LLM-driven document rewriting. Word formatting is a structured Open XML problem: styles, section properties, numbering, fields, and relationships need deterministic handling. LLM output may help classify text later, but it should not directly edit `.docx` packages.

## Why The Content Document Is The Base

The formatter starts from the content document instead of rebuilding a new document from plain text. This preserves package relationships and complex content as much as possible:

- images
- tables
- equations
- footnotes/endnotes
- bookmarks
- comments
- fields
- embedded objects

The formatter then imports relevant template styles and applies mapped paragraph styles to the existing document structure.

## Future AI / Local Inference Extension Point

AI or local inference can be added between `content_analyzer` and `style_mapper`:

```text
content_structure.json -> optional classifier -> revised roles/confidence -> mapping
```

The safe contract is: AI may suggest roles or rules as JSON; deterministic code still performs the final `.docx` modification.

## Future Windows Word Automation

`core/word_automation.py` contains the reserved interface. A later Windows implementation can use Microsoft Word COM automation to:

- open the generated document in Word
- update fields and TOC
- repaginate
- save through Word
- detect repair prompts or layout failures

Mac development remains useful for package-level `.docx` generation and validation, but final layout authority should be Microsoft Word, preferably Windows Word in later stages.
