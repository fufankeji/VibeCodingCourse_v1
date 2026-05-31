"""Shared data structures and constants for water review."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

@dataclass
class ParsedBlock:
    block_id: str
    page: int
    bbox: list[float]
    text: str
    type: str
    section_hint: str
    char_start: int
    char_end: int
    html: str = ""
    image_path: str = ""
    mineru_index: int | None = None
    mineru_sub_type: str = ""
    page_size: list[float] = field(default_factory=list)
    child_types: list[str] = field(default_factory=list)
    span_types: list[str] = field(default_factory=list)
    line_bboxes: list[list[float]] = field(default_factory=list)
    span_bboxes: list[list[float]] = field(default_factory=list)
    parent_section: str = ""
    caption: str = ""
    atomic_index: int = 0


@dataclass
class ReviewChunk:
    chunk_id: str
    text: str
    section: str
    page_range: list[int]
    bbox_list: list[dict[str, Any]]
    table_refs: list[str]
    metadata: dict[str, Any]
    char_start: int
    char_end: int
    embedding_text: str = ""


WATER_FIELDS = [
    "project_name",
    "construction_unit",
    "construction_location",
    "project_nature",
    "key_prevention_or_control_area",
    "disturbed_area",
    "land_area",
    "prevention_responsibility_area",
    "zone_area",
    "excavation_volume",
    "fill_volume",
    "borrow_volume",
    "spoil_volume",
    "comprehensive_utilization",
    "spoil_destination",
    "topsoil_stripping",
    "topsoil_preservation",
    "topsoil_backfill",
    "temp_soil_stockpile",
    "borrow_area",
    "spoil_area",
    "construction_road",
    "prevention_measures",
    "monitoring",
    "schedule_arrangement",
    "investment_estimate",
]


SECTION_KEYWORDS = {
    "项目概况": ["项目概况", "综合说明", "工程概况"],
    "防治责任范围": ["防治责任范围", "扰动范围", "占地"],
    "水土流失分析": ["水土流失", "流失预测", "流失现状"],
    "防治措施": ["水土保持措施", "防治措施", "工程措施", "植物措施"],
    "监测": ["水土保持监测", "监测"],
    "投资估算": ["投资估算", "效益分析", "投资"],
    "结论": ["结论", "建议"],
}


RULES = [
    {
        "rule_id": "SWC-FORM-001",
        "rule_name": "必备章节完整性检查",
        "rule_category": "形式类",
        "severity": "HIGH",
        "expected": "报告应包含项目概况、防治责任范围、防治措施、监测、投资估算、结论等核心章节",
    },
    {
        "rule_id": "SWC-FIELD-001",
        "rule_name": "项目基础信息完整性检查",
        "rule_category": "形式类",
        "severity": "MEDIUM",
        "expected": "项目名称、建设单位、建设地点、建设性质应有明确表述",
    },
    {
        "rule_id": "SWC-TECH-001",
        "rule_name": "扰动面积明确性检查",
        "rule_category": "技术类",
        "severity": "HIGH",
        "expected": "应明确扰动地表面积或防治责任范围面积",
    },
    {
        "rule_id": "SWC-TECH-002",
        "rule_name": "土石方平衡一致性检查",
        "rule_category": "一致性类",
        "severity": "HIGH",
        "expected": "挖方 + 借方 应与 填方 + 弃方 基本平衡",
    },
    {
        "rule_id": "SWC-TECH-003",
        "rule_name": "表土保护措施检查",
        "rule_category": "技术类",
        "severity": "MEDIUM",
        "expected": "涉及扰动地表时应说明表土剥离、保存或回覆措施",
    },
    {
        "rule_id": "SWC-TECH-004",
        "rule_name": "弃方与弃渣场匹配检查",
        "rule_category": "技术类",
        "severity": "HIGH",
        "expected": "存在弃方时应说明弃渣场或弃土去向",
    },
    {
        "rule_id": "SWC-ATTR-001",
        "rule_name": "区域属性明确性检查",
        "rule_category": "项目属性判定",
        "severity": "LOW",
        "expected": "应说明是否位于重点预防区、重点治理区或易发生水土流失区域",
    },
]

BACKEND_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BACKEND_DIR / "data"
DEFAULT_MINERU_JSON = DATA_DIR / "MinerU_1 北京航空航天大学沙河校区图书馆项目水土保持方案.json"
DEFAULT_MINERU_MD = DATA_DIR / "北京航空航天大学沙河校区图书馆项目-mineru.md"
DEFAULT_RULE_SET = DATA_DIR / "水土保持方案审查规则集.json"
QUICK_VALIDATION_ISSUE_COUNT = 10
SEMANTIC_CHUNK_MAX_CHARS = 1100
SEMANTIC_CHUNK_OVERLAP_BLOCKS = 1
EVIDENCE_WINDOW_BLOCK_RADIUS = 1
TABLE_ROW_MAX_ROWS_PER_TABLE = 80
TABLE_ROW_INCLUDE_KEYWORDS = (
    "弃渣",
    "弃土",
    "弃方",
    "取土",
    "取料",
    "土石方",
    "表土",
    "占地",
    "防治责任",
    "防治措施",
    "监测",
    "扰动",
)
TABLE_ROW_EXCLUDE_HINTS = ("工程单价", "机械台时", "概算附表", "单价汇总", "附表")
