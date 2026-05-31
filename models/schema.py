from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RFonts(BaseModel):
    ascii: Optional[str] = None
    hAnsi: Optional[str] = None
    eastAsia: Optional[str] = None
    cs: Optional[str] = None


class ParagraphProperties(BaseModel):
    alignment: Optional[str] = None
    first_line_indent_twips: Optional[int] = None
    left_indent_twips: Optional[int] = None
    right_indent_twips: Optional[int] = None
    space_before_twips: Optional[int] = None
    space_after_twips: Optional[int] = None
    line_spacing: Optional[str] = None
    rfonts: RFonts = Field(default_factory=RFonts)
    size_half_points: Optional[int] = None
    bold: Optional[bool] = None
    italic: Optional[bool] = None


class StyleProfile(BaseModel):
    style_id: str
    style_name: str
    style_type: str
    based_on: Optional[str] = None
    is_default: bool = False
    paragraph_count: int = 0
    sample_texts: List[str] = Field(default_factory=list)
    properties: ParagraphProperties = Field(default_factory=ParagraphProperties)


class SectionProfile(BaseModel):
    index: int
    page_width_twips: Optional[int] = None
    page_height_twips: Optional[int] = None
    orientation: Optional[str] = None
    margin_top_twips: Optional[int] = None
    margin_bottom_twips: Optional[int] = None
    margin_left_twips: Optional[int] = None
    margin_right_twips: Optional[int] = None
    header_twips: Optional[int] = None
    footer_twips: Optional[int] = None
    gutter_twips: Optional[int] = None


class TemplateQuality(BaseModel):
    total_paragraphs: int = 0
    styled_paragraphs: int = 0
    direct_paragraph_format_count: int = 0
    direct_run_format_count: int = 0
    direct_format_ratio: float = 0.0
    reliable_style_source: bool = True
    warnings: List[str] = Field(default_factory=list)


class FormatProfile(BaseModel):
    source_path: str
    extracted_at: str = Field(default_factory=now_iso)
    styles: List[StyleProfile] = Field(default_factory=list)
    sections: List[SectionProfile] = Field(default_factory=list)
    style_usage: Dict[str, int] = Field(default_factory=dict)
    numbering_ids: List[str] = Field(default_factory=list)
    header_footer_parts: List[str] = Field(default_factory=list)
    advanced_features: Dict[str, Any] = Field(default_factory=dict)
    template_quality: TemplateQuality = Field(default_factory=TemplateQuality)


class ParagraphBlock(BaseModel):
    index: int
    text_preview: str
    role: str
    confidence: float
    current_style_id: Optional[str] = None
    current_style_name: Optional[str] = None
    has_direct_paragraph_format: bool = False
    has_direct_run_format: bool = False
    notes: List[str] = Field(default_factory=list)


class ContentStructure(BaseModel):
    source_path: str
    generated_at: str = Field(default_factory=now_iso)
    blocks: List[ParagraphBlock] = Field(default_factory=list)
    role_counts: Dict[str, int] = Field(default_factory=dict)
    advanced_features: Dict[str, Any] = Field(default_factory=dict)


class StyleCandidate(BaseModel):
    style_id: str
    style_name: str
    score: float = 0.0
    sample_texts: List[str] = Field(default_factory=list)
    reason: Optional[str] = None


class MappingEntry(BaseModel):
    role: str = Field(..., min_length=1)
    style_id: Optional[str] = None
    style_name: Optional[str] = None
    confidence: float = 0.0
    source: str = "generated"
    required: bool = False
    warning: Optional[str] = None
    sample_texts: List[str] = Field(default_factory=list)
    target_style_samples: List[str] = Field(default_factory=list)
    confidence_reason: Optional[str] = None
    candidate_styles: List["StyleCandidate"] = Field(default_factory=list)

    @field_validator("confidence")
    @classmethod
    def confidence_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")
        return v


class StyleMapping(BaseModel):
    generated_at: str = Field(default_factory=now_iso)
    entries: List[MappingEntry] = Field(default_factory=list)
    low_confidence_threshold: float = 0.75
    notes: List[str] = Field(default_factory=list)

    def by_role(self) -> Dict[str, MappingEntry]:
        return {entry.role: entry for entry in self.entries}


class ReadinessResult(BaseModel):
    status: str = "需复核"
    score: int = 0
    risk_level: str = "high"
    blocking_items: List[str] = Field(default_factory=list)
    manual_review_items: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    generated_at: str = Field(default_factory=now_iso)
    source_stage: str = "inspection"


class DoctorCheck(BaseModel):
    name: str
    status: str
    message: str
    suggested_fix: Optional[str] = None


class DoctorResult(BaseModel):
    passed: bool = False
    generated_at: str = Field(default_factory=now_iso)
    summary: Dict[str, int] = Field(default_factory=dict)
    checks: List[DoctorCheck] = Field(default_factory=list)


class ValidationIssue(BaseModel):
    severity: str
    code: str
    message: str
    paragraph_index: Optional[int] = None
    text_preview: Optional[str] = None
    current_style_id: Optional[str] = None
    current_style_name: Optional[str] = None
    expected_style_id: Optional[str] = None
    expected_style_name: Optional[str] = None
    confidence: Optional[float] = None
    suggested_fix: Optional[str] = None


class ValidationResult(BaseModel):
    output_path: Optional[str] = None
    generated_at: str = Field(default_factory=now_iso)
    passed: bool = False
    summary: Dict[str, int] = Field(default_factory=dict)
    issues: List[ValidationIssue] = Field(default_factory=list)
    readiness: Optional[ReadinessResult] = None
