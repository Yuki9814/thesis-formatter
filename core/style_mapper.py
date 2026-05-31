from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, Optional

import yaml

from models import ContentStructure, FormatProfile, MappingEntry, StyleCandidate, StyleMapping, StyleProfile


ROLE_ALIASES: Dict[str, Iterable[str]] = {
    "heading_1": ("heading 1", "标题 1", "标题1", "一级", "chapter", "thesis heading 1"),
    "heading_2": ("heading 2", "标题 2", "标题2", "二级", "thesis heading 2"),
    "heading_3": ("heading 3", "标题 3", "标题3", "三级", "thesis heading 3"),
    "body": ("正文", "body", "normal", "text", "论文正文"),
    "abstract": ("摘要", "abstract"),
    "keywords": ("关键词", "关键字", "keyword"),
    "figure_caption": ("图题", "figure", "caption", "题注"),
    "table_caption": ("表题", "table", "caption", "题注"),
    "reference_item": ("参考文献", "reference", "bibliography"),
    "reference_heading": ("参考文献", "reference", "references", "bibliography"),
    "appendix": ("附录", "appendix"),
    "toc": ("目录", "toc", "contents"),
    "equation": ("公式", "equation"),
}


def _load_rules(rules_path: Optional[str | Path]) -> Dict[str, object]:
    if not rules_path:
        return {}
    path = Path(rules_path)
    if not path.exists():
        raise FileNotFoundError(path)
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _style_lookup(profile: FormatProfile) -> Dict[str, StyleProfile]:
    by_id = {style.style_id: style for style in profile.styles}
    by_name = {style.style_name: style for style in profile.styles}
    return {**by_name, **by_id}


def _find_by_rule(role: str, profile: FormatProfile, rules: Dict[str, object]) -> Optional[MappingEntry]:
    style_map = rules.get("style_map") or {}
    if not isinstance(style_map, dict) or role not in style_map:
        return None
    requested = str(style_map[role])
    lookup = _style_lookup(profile)
    style = lookup.get(requested)
    if style is None:
        return MappingEntry(
            role=role,
            confidence=0.0,
            source="rules.yaml",
            warning=f"Rule requested style '{requested}', but it was not found in the template.",
            confidence_reason="rules.yaml 指向的样式不存在，需要修正规则或模板。",
        )
    return MappingEntry(
        role=role,
        style_id=style.style_id,
        style_name=style.style_name,
        confidence=1.0,
        source="rules.yaml",
        confidence_reason="来自 rules.yaml 显式指定，优先级最高。",
    )


def _score_style(role: str, style: StyleProfile) -> float:
    haystack = f"{style.style_id} {style.style_name}".lower()
    aliases = ROLE_ALIASES.get(role, ())
    score = 0.0
    for alias in aliases:
        if alias.lower() in haystack:
            score = max(score, 0.92)
    if role.startswith("heading") and style.style_type == "paragraph" and style.paragraph_count:
        score = max(score, min(0.75, 0.45 + style.paragraph_count / 50))
    if role == "body" and style.style_id.lower() in {"normal", "bodytext"}:
        score = max(score, 0.85)
    if role in {"figure_caption", "table_caption"} and "caption" in haystack:
        score = max(score, 0.82)
    return score


def _score_reason(role: str, style: StyleProfile, score: float) -> str:
    haystack = f"{style.style_id} {style.style_name}".lower()
    aliases = [alias for alias in ROLE_ALIASES.get(role, ()) if alias.lower() in haystack]
    if aliases:
        return f"样式名或 ID 命中关键词：{', '.join(aliases[:3])}。"
    if role.startswith("heading") and style.paragraph_count:
        return "模板中该段落样式已有标题类使用痕迹。"
    if role == "body" and style.style_id.lower() in {"normal", "bodytext"}:
        return "正文角色回落到 Word 常见正文样式。"
    if score > 0:
        return "根据模板样式类型和使用次数生成的候选。"
    return "未找到明确匹配证据，仅作为备选样式展示。"


def _candidate_styles(role: str, profile: FormatProfile, limit: int = 5) -> list[StyleCandidate]:
    candidates = [style for style in profile.styles if style.style_type == "paragraph"]
    scored = sorted(
        ((_score_style(role, style), style) for style in candidates),
        key=lambda item: (item[0], item[1].paragraph_count),
        reverse=True,
    )
    result = []
    for score, style in scored[:limit]:
        result.append(
            StyleCandidate(
                style_id=style.style_id,
                style_name=style.style_name,
                score=round(score, 2),
                sample_texts=style.sample_texts[:3],
                reason=_score_reason(role, style, score),
            )
        )
    return result


def _role_samples(structure: ContentStructure, role: str) -> list[str]:
    samples = []
    for block in structure.blocks:
        if block.role == role and block.text_preview:
            samples.append(block.text_preview)
        if len(samples) >= 3:
            break
    return samples


def _enrich_entry(entry: MappingEntry, profile: FormatProfile, structure: ContentStructure) -> MappingEntry:
    entry.sample_texts = _role_samples(structure, entry.role)
    entry.candidate_styles = _candidate_styles(entry.role, profile)
    if entry.style_id:
        style = next((item for item in profile.styles if item.style_id == entry.style_id), None)
        if style:
            entry.target_style_samples = style.sample_texts[:3]
    if not entry.confidence_reason:
        if entry.source == "rules.yaml" and entry.style_id:
            entry.confidence_reason = "来自 rules.yaml 显式指定，优先级最高。"
        elif entry.warning:
            entry.confidence_reason = entry.warning
        elif entry.style_id:
            entry.confidence_reason = "根据角色关键词、样式名和模板使用痕迹自动匹配。"
        else:
            entry.confidence_reason = "未找到可用目标样式，需要人工补齐。"
    return entry


def _find_by_alias(role: str, profile: FormatProfile) -> MappingEntry:
    candidates = [style for style in profile.styles if style.style_type == "paragraph"]
    scored = sorted(((_score_style(role, style), style) for style in candidates), key=lambda item: item[0], reverse=True)
    if scored and scored[0][0] > 0:
        score, style = scored[0]
        warning = None if score >= 0.75 else "Low confidence style match; please confirm before formatting."
        return MappingEntry(
            role=role,
            style_id=style.style_id,
            style_name=style.style_name,
            confidence=round(score, 2),
            source="generated",
            warning=warning,
            confidence_reason=_score_reason(role, style, score),
        )
    return MappingEntry(
        role=role,
        confidence=0.0,
        source="generated",
        warning="No matching style found in template.",
        confidence_reason="模板中没有找到与该角色匹配的段落样式。",
    )


def build_style_mapping(
    profile: FormatProfile,
    structure: ContentStructure,
    rules_path: Optional[str | Path] = None,
) -> StyleMapping:
    rules = _load_rules(rules_path)
    roles = sorted(role for role, count in structure.role_counts.items() if count > 0 and role != "body")
    if structure.role_counts.get("body", 0):
        roles.append("body")
    entries = []
    notes = []
    if not profile.template_quality.reliable_style_source:
        notes.extend(profile.template_quality.warnings)
    for role in roles:
        entry = _find_by_rule(role, profile, rules) or _find_by_alias(role, profile)
        entry.required = role in structure.role_counts and structure.role_counts[role] > 0
        entries.append(_enrich_entry(entry, profile, structure))
    return StyleMapping(entries=entries, notes=notes)


def mapping_policy_issues(mapping: StyleMapping, strict: bool = False) -> list[MappingEntry]:
    issues = []
    for entry in mapping.entries:
        if not entry.required:
            continue
        if not entry.style_id:
            issues.append(entry)
            continue
        if strict and entry.confidence < mapping.low_confidence_threshold:
            issues.append(entry)
    return issues


def validate_mapping_consistency(profile: FormatProfile, mapping: StyleMapping) -> list[str]:
    """Check if all style_ids in mapping exist in the profile styles."""
    errors = []
    template_style_ids = {style.style_id for style in profile.styles}
    for entry in mapping.entries:
        if entry.style_id and entry.style_id not in template_style_ids:
            errors.append(f"Role '{entry.role}' maps to missing style ID '{entry.style_id}'.")
    return errors
