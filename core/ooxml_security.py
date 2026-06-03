from __future__ import annotations

from pathlib import PurePosixPath
from posixpath import normpath
from urllib.parse import urlparse

from models import SecurityFinding

from .docx_loader import DocxError, list_parts, read_part, validate_docx_path
from .xml_utils import parse_xml


REL_NS = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}


def _finding(
    severity: str,
    code: str,
    message: str,
    *,
    part: str | None = None,
    suggested_fix: str | None = None,
    label: str | None = None,
) -> SecurityFinding:
    visible_part = f"{label}:{part}" if label and part else part
    return SecurityFinding(
        severity=severity,
        code=code,
        part=visible_part,
        message=message,
        suggested_fix=suggested_fix,
    )


def _external_relationship_severity(target: str, rel_type: str) -> tuple[str, str]:
    parsed = urlparse(target)
    rel_type_lower = rel_type.lower()
    if parsed.scheme in {"http", "https"} and rel_type_lower.endswith("/hyperlink"):
        return "warning", "security.external_hyperlink"
    return "error", "security.external_relationship"


def _relationship_base(rel_part: str) -> str:
    if rel_part == "_rels/.rels":
        return ""
    if "/_rels/" not in rel_part or not rel_part.endswith(".rels"):
        return ""
    source = rel_part.replace("/_rels/", "/", 1)[: -len(".rels")]
    return str(PurePosixPath(source).parent)


def _unsafe_internal_target(rel_part: str, target: str) -> bool:
    if not target or target.startswith(("/", "\\")) or "\\" in target:
        return True
    base = _relationship_base(rel_part)
    combined = normpath(f"{base}/{target}" if base else target)
    return combined in {".", ".."} or combined.startswith("../") or "/../" in combined


def _relationship_findings(path, rel_part: str, label: str | None) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    root = parse_xml(read_part(path, rel_part))
    for rel in root.findall("./rel:Relationship", namespaces=REL_NS):
        target = rel.get("Target") or ""
        rel_type = rel.get("Type") or ""
        target_mode = rel.get("TargetMode")
        rel_type_lower = rel_type.lower()
        target_lower = target.lower()
        if target_mode == "External":
            severity, code = _external_relationship_severity(target, rel_type)
            findings.append(
                _finding(
                    severity,
                    code,
                    "文档包含外部关系，交付前需要确认不会泄露本地路径或加载外部资源。",
                    part=rel_part,
                    suggested_fix="移除外部关系，或在 Word 中确认该链接确实需要保留。",
                    label=label,
                )
            )
        if "afchunk" in rel_type_lower:
            findings.append(
                _finding(
                    "error",
                    "security.alt_chunk",
                    "文档包含 altChunk 导入内容，当前版本不安全处理。",
                    part=rel_part,
                    suggested_fix="在 Word 中清理 altChunk 内容后重新保存为普通 .docx。",
                    label=label,
                )
            )
        if "activex" in rel_type_lower:
            findings.append(
                _finding(
                    "error",
                    "security.activex",
                    "文档包含 ActiveX 组件，已阻断处理。",
                    part=rel_part,
                    suggested_fix="删除 ActiveX 组件后重新运行。",
                    label=label,
                )
            )
        if "oleobject" in rel_type_lower or "oleobject" in target_lower or "embeddings/" in target_lower:
            findings.append(
                _finding(
                    "warning",
                    "security.embedded_object",
                    "文档包含嵌入对象，交付前需要在 Microsoft Word 中人工复核。",
                    part=rel_part,
                    suggested_fix="确认嵌入对象安全且交付文件允许保留。",
                    label=label,
                )
            )
        if target and target_mode != "External":
            if _unsafe_internal_target(rel_part, target):
                findings.append(
                    _finding(
                        "error",
                        "security.relationship_path",
                        "文档关系指向不安全的内部路径。",
                        part=rel_part,
                        suggested_fix="清理异常 relationship target 后重新保存文档。",
                        label=label,
                    )
                )
    return findings


def scan_docx_security(path, label: str | None = None) -> list[SecurityFinding]:
    docx_path = validate_docx_path(path)
    findings: list[SecurityFinding] = []
    parts = list_parts(docx_path)
    for part in parts:
        lower = part.lower()
        if lower.endswith("vbaproject.bin"):
            findings.append(
                _finding(
                    "error",
                    "security.macro",
                    "文档包含宏工程，当前版本不处理带宏风险的文档。",
                    part=part,
                    suggested_fix="另存为不含宏的 .docx 后重新运行。",
                    label=label,
                )
            )
        if "/activex/" in lower or lower.startswith("word/activex/"):
            findings.append(
                _finding(
                    "error",
                    "security.activex",
                    "文档包含 ActiveX 组件，已阻断处理。",
                    part=part,
                    suggested_fix="删除 ActiveX 组件后重新运行。",
                    label=label,
                )
            )
        if "altchunk" in lower or lower.startswith("word/afchunk"):
            findings.append(
                _finding(
                    "error",
                    "security.alt_chunk",
                    "文档包含 altChunk 导入内容，当前版本不安全处理。",
                    part=part,
                    suggested_fix="在 Word 中清理 altChunk 内容后重新保存为普通 .docx。",
                    label=label,
                )
            )
        if "/embeddings/" in lower or lower.startswith("word/embeddings/"):
            findings.append(
                _finding(
                    "warning",
                    "security.embedded_object",
                    "文档包含嵌入对象，交付前需要在 Microsoft Word 中人工复核。",
                    part=part,
                    suggested_fix="确认嵌入对象安全且交付文件允许保留。",
                    label=label,
                )
            )
        if lower.endswith(".rels"):
            findings.extend(_relationship_findings(docx_path, part, label))
    return findings


def raise_for_blocking_findings(findings: list[SecurityFinding]) -> None:
    blocked = [finding for finding in findings if finding.severity == "error"]
    if blocked:
        codes = ", ".join(sorted({finding.code for finding in blocked}))
        raise DocxError(f"文档安全检查未通过：{codes}")
