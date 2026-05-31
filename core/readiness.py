from __future__ import annotations

from collections import Counter
from typing import Iterable

from models import ContentStructure, FormatProfile, ReadinessResult, StyleMapping, ValidationIssue


ADVANCED_REVIEW_MESSAGES = {
    "has_toc_field": "检测到目录字段，交付前需在 Microsoft Word 中更新目录。",
    "has_cross_reference_fields": "检测到交叉引用或页码引用，交付前需在 Microsoft Word 中更新域。",
    "has_omml_equations": "检测到公式，交付前需在 Microsoft Word 中逐处目检。",
    "has_footnotes": "检测到脚注，交付前需检查脚注编号和分页。",
    "has_endnotes": "检测到尾注，交付前需检查尾注编号和位置。",
    "has_bookmarks": "检测到书签，交付前需检查书签和交叉引用是否仍有效。",
    "has_comments": "检测到批注，交付前需确认是否清理批注。",
}


def _dedupe(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _mapping_blockers(mapping: StyleMapping) -> list[str]:
    return [
        f"角色 {entry.role} 缺少目标样式，无法可靠格式化。"
        for entry in mapping.entries
        if entry.required and not entry.style_id
    ]


def _mapping_reviews(mapping: StyleMapping) -> list[str]:
    reviews = []
    for entry in mapping.entries:
        if not entry.required or not entry.style_id:
            continue
        if entry.confidence < mapping.low_confidence_threshold:
            reviews.append(
                f"角色 {entry.role} 的映射置信度为 {entry.confidence:.2f}，需要人工确认目标样式。"
            )
    return reviews


def _content_reviews(structure: ContentStructure) -> list[str]:
    reviews = []
    for key, message in ADVANCED_REVIEW_MESSAGES.items():
        if structure.advanced_features.get(key):
            reviews.append(message)
    if structure.advanced_features.get("media_part_count", 0):
        reviews.append("检测到图片或媒体资源，交付前需确认图片、题注和位置未丢失。")
    return reviews


def _template_reviews(profile: FormatProfile) -> list[str]:
    reviews = list(profile.template_quality.warnings)
    if not profile.sections:
        reviews.append("模板没有检测到页面设置，交付前需人工确认纸张和页边距。")
    if profile.advanced_features.get("header_footer_part_count", 0):
        reviews.append("模板包含页眉页脚，交付前需确认输出文档页眉页脚符合学校要求。")
    return reviews


def _status(score: int, blocking_items: list[str], manual_review_items: list[str]) -> tuple[str, str]:
    if blocking_items or score < 60:
        return "不建议交付", "high"
    if manual_review_items or score < 90:
        return "需复核", "medium"
    return "可交付", "low"


def _score(blocking_items: list[str], manual_review_items: list[str]) -> int:
    value = 100
    value -= min(len(blocking_items), 4) * 25
    value -= min(len(manual_review_items), 6) * 8
    return max(0, min(100, value))


def _next_actions(blocking_items: list[str], manual_review_items: list[str], stage: str) -> list[str]:
    if blocking_items:
        return [
            "先修复阻塞项，再重新运行检查或格式化。",
            "优先打开 mapping JSON 或 GUI 映射页，补齐缺失目标样式。",
            "如果模板质量较差，换用干净 Word 模板后重新检查。",
        ]
    if stage == "delivery":
        actions = ["用 Microsoft Word 打开输出文档，按交付检查清单逐项复核。"]
    else:
        actions = ["确认低置信度映射和模板质量提示后，再执行格式化。"]
    if manual_review_items:
        actions.append("处理所有人工复核项；字段、目录和页码需在 Word 内更新。")
    else:
        actions.append("保留报告和检查清单，作为交付前复核记录。")
    return actions


def build_inspection_readiness(
    profile: FormatProfile,
    structure: ContentStructure,
    mapping: StyleMapping,
) -> ReadinessResult:
    blocking_items = _dedupe(_mapping_blockers(mapping))
    manual_review_items = _dedupe(
        [*_mapping_reviews(mapping), *_template_reviews(profile), *_content_reviews(structure)]
    )
    score = _score(blocking_items, manual_review_items)
    status, risk_level = _status(score, blocking_items, manual_review_items)
    return ReadinessResult(
        status=status,
        score=score,
        risk_level=risk_level,
        blocking_items=blocking_items,
        manual_review_items=manual_review_items,
        next_actions=_next_actions(blocking_items, manual_review_items, "inspection"),
        source_stage="inspection",
    )


def build_delivery_readiness(issues: list[ValidationIssue]) -> ReadinessResult:
    counts = Counter(issue.severity for issue in issues)
    blocking_items = _dedupe(
        f"{issue.code}: {issue.message}" for issue in issues if issue.severity == "error"
    )
    manual_review_items = _dedupe(
        f"{issue.code}: {issue.message}"
        for issue in issues
        if issue.severity in {"warning", "info"}
    )
    score = _score(blocking_items, manual_review_items)
    if counts.get("warning", 0) > 8 and not blocking_items:
        score = min(score, 68)
    status, risk_level = _status(score, blocking_items, manual_review_items)
    return ReadinessResult(
        status=status,
        score=score,
        risk_level=risk_level,
        blocking_items=blocking_items,
        manual_review_items=manual_review_items,
        next_actions=_next_actions(blocking_items, manual_review_items, "delivery"),
        source_stage="delivery",
    )


def readiness_for_failure(message: str) -> ReadinessResult:
    blocking_items = [message]
    return ReadinessResult(
        status="不建议交付",
        score=0,
        risk_level="high",
        blocking_items=blocking_items,
        manual_review_items=[],
        next_actions=_next_actions(blocking_items, [], "delivery"),
        source_stage="delivery",
    )
