"""Structured review-rule schema for water-soil review.

The source rule set is still a flat JSON file.  This module normalizes it into
the product review hierarchy:

review topic -> review item -> review rule -> evidence scope -> execution.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.services.review_executor_service import execute_check_item_precheck


REVIEW_LOGIC_LABELS = {
    "format_review": "格式审查",
    "content_review": "内容审查",
    "consistency_review": "一致性审查",
    "table_calculation_review": "表内计算审查",
    "formula_calculation_review": "公式计算审查",
    "business_logic_review": "业务逻辑审查",
}


TOPIC_ALIASES = {
    "项目概况类": "项目概况审查",
    "评价与选址类": "水土保持评价与选址审查",
    "防治责任范围类": "防治责任范围审查",
    "防治措施类": "防治措施体系审查",
    "监测类": "水土保持监测审查",
    "投资估算类": "投资估算与效益审查",
    "区域特别要求": "区域特别要求审查",
    "形式类": "报告形式与完整性审查",
    "技术类": "技术方案审查",
    "一致性类": "关键数据一致性审查",
    "项目属性判定": "项目属性与适用规则审查",
}


SCMC_TOPIC_SPECS = [
    {"id": "scmc-001", "name": "项目总投资", "check_item_count": 11, "reference_error_count": 3, "main_review_types": ["一致性审查", "表内计算审查", "公式计算审查"], "keywords": ["总投资", "投资", "概算", "估算", "措施单价", "费用", "价格水平年"]},
    {"id": "scmc-002", "name": "土石方总量", "check_item_count": 5, "reference_error_count": 1, "main_review_types": ["一致性审查", "表内计算审查", "公式计算审查"], "keywords": ["土石方总量", "土石方", "土石方平衡", "土石方数量", "土石方流向", "调配关系"]},
    {"id": "scmc-003", "name": "工程占地", "check_item_count": 14, "reference_error_count": 5, "main_review_types": ["一致性审查", "表内计算审查", "业务逻辑审查"], "keywords": ["工程占地", "征占地", "占地", "占地面积", "占地类型", "占地性质", "永久征地", "临时占地"]},
    {"id": "scmc-004", "name": "取土场类型、取土深度、取土场占地类型", "check_item_count": 2, "reference_error_count": 0, "main_review_types": ["格式审查", "内容审查"], "keywords": ["取土场", "取土场型式", "取土深度", "取土场占地类型", "借方来源"]},
    {"id": "scmc-005", "name": "施工便道及其分项指标", "check_item_count": 1, "reference_error_count": 1, "main_review_types": ["业务逻辑审查"], "keywords": ["施工便道", "施工道路", "施工便道及其分项指标"]},
    {"id": "scmc-006", "name": "设计水平年", "check_item_count": 3, "reference_error_count": 1, "main_review_types": ["一致性审查", "表内计算审查", "业务逻辑审查"], "keywords": ["设计水平年", "防治目标", "指标值", "水土流失防治指标值"]},
    {"id": "scmc-007", "name": "总工期、开完工时间", "check_item_count": 5, "reference_error_count": 0, "main_review_types": ["一致性审查", "业务逻辑审查"], "keywords": ["总工期", "开工", "完工", "施工时序", "实施时段", "实施进度", "建设计划"]},
    {"id": "scmc-008", "name": "综合监测点位、工程措施监测点位、土壤流失量监测点位", "check_item_count": 3, "reference_error_count": 0, "main_review_types": ["一致性审查", "表内计算审查", "业务逻辑审查"], "keywords": ["监测点", "监测点位", "点位布设", "工程措施监测点位", "土壤流失量监测点位", "综合监测点位"]},
    {"id": "scmc-009", "name": "防治分区", "check_item_count": 5, "reference_error_count": 1, "main_review_types": ["一致性审查", "格式审查", "业务逻辑审查"], "keywords": ["防治分区", "防治区", "防治区划分", "分区防治", "水土流失类型"]},
    {"id": "scmc-010", "name": "植物措施", "check_item_count": 15, "reference_error_count": 2, "main_review_types": ["业务逻辑审查", "一致性审查", "表内计算审查"], "keywords": ["植物措施", "植物配置", "林草", "植被", "乔灌草", "乡土树种", "乡土草种", "灌溉设施"]},
    {"id": "scmc-011", "name": "临时措施", "check_item_count": 20, "reference_error_count": 6, "main_review_types": ["一致性审查", "格式审查", "内容审查", "业务逻辑审查"], "keywords": ["临时措施", "临时防护", "临时堆土", "裸露面防护", "降尘", "车轮冲洗", "运输车辆"]},
    {"id": "scmc-012", "name": "挖方", "check_item_count": 3, "reference_error_count": 1, "main_review_types": ["一致性审查", "表内计算审查", "公式计算审查"], "keywords": ["挖方", "开挖量", "土石方挖填"]},
    {"id": "scmc-013", "name": "借方", "check_item_count": 5, "reference_error_count": 0, "main_review_types": ["一致性审查", "格式审查", "公式计算审查"], "keywords": ["借方", "取土量", "外借", "借方来源", "外借土石方量"]},
    {"id": "scmc-014", "name": "水土保持敏感区", "check_item_count": 2, "reference_error_count": 0, "main_review_types": ["一致性审查", "业务逻辑审查"], "keywords": ["敏感区", "生态脆弱区", "水土保持敏感区", "避让", "黑土", "区域敏感性", "项目选址"]},
    {"id": "scmc-015", "name": "原地貌土壤侵蚀模数", "check_item_count": 7, "reference_error_count": 1, "main_review_types": ["一致性审查", "表内计算审查", "格式审查"], "keywords": ["原地貌", "土壤侵蚀模数", "侵蚀模数", "原地貌土壤侵蚀模数"]},
    {"id": "scmc-016", "name": "水力侵蚀下一般扰动地表翻扰型土壤侵蚀模数计算", "check_item_count": 5, "reference_error_count": 0, "main_review_types": ["一致性审查", "表内计算审查", "公式计算审查"], "keywords": ["水力侵蚀", "扰动地表", "翻扰型", "土壤侵蚀模数计算"]},
    {"id": "scmc-017", "name": "土壤侵蚀强度", "check_item_count": 9, "reference_error_count": 2, "main_review_types": ["一致性审查", "表内计算审查", "内容审查"], "keywords": ["土壤侵蚀强度", "水土流失强度", "侵蚀强度"]},
    {"id": "scmc-018", "name": "容许土壤流失量", "check_item_count": 1, "reference_error_count": 0, "main_review_types": ["一致性审查"], "keywords": ["容许土壤流失量", "容许流失量"]},
    {"id": "scmc-019", "name": "表土保护率", "check_item_count": 7, "reference_error_count": 0, "main_review_types": ["格式审查", "内容审查", "一致性审查", "公式计算审查"], "keywords": ["表土保护率", "表土剥离", "表土保存", "表土回覆", "表土资源", "表层土"]},
    {"id": "scmc-020", "name": "林草植被恢复率", "check_item_count": 4, "reference_error_count": 1, "main_review_types": ["公式计算审查", "一致性审查", "业务逻辑审查"], "keywords": ["林草植被恢复率", "林草覆盖率", "植被恢复率", "植被恢复"]},
]


SECTION_SCOPE_RULES = [
    ("项目概况", ["项目概况", "建设内容", "总体布置", "征占地", "土石方", "拆迁", "依托工程"]),
    ("水土保持评价", ["评价", "选址", "水土保持评价", "生态脆弱区", "敏感区", "制约性因素"]),
    ("防治责任范围", ["防治责任范围", "扰动", "占地", "防治分区"]),
    ("水土流失预测", ["水土流失预测", "流失量", "侵蚀", "预测"]),
    ("防治措施", ["防治措施", "工程措施", "植物措施", "临时措施", "表土", "弃渣", "拦挡", "排水"]),
    ("水土保持监测", ["监测", "监测点", "监测频次", "监测内容"]),
    ("投资估算", ["投资", "估算", "概算", "效益"]),
    ("附件附图", ["附图", "附件", "图件", "支撑材料", "立项文件", "主体设计文件", "批复"]),
]


TABLE_KEYWORDS = ["表", "统计", "面积", "土石方", "平衡", "投资", "工程量", "数量", "清单", "占地"]
FORMULA_KEYWORDS = ["计算", "公式", "率", "系数", "标准", "等级", "拦渣率", "防治指标", "林草覆盖率", "土壤流失量"]
CONSISTENCY_KEYWORDS = ["一致", "衔接", "匹配", "平衡", "关系", "口径", "对应", "统一"]
FORMAT_KEYWORDS = ["章节", "格式", "完整性", "目录", "附图", "附件", "签章", "报批", "编制"]
BUSINESS_KEYWORDS = ["合规", "选址", "避让", "准入", "责任", "措施", "布设", "防治", "监测", "施工", "验收"]


def normalize_review_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return flat rules enriched with hierarchy, scope and execution metadata."""
    return [normalize_review_rule(rule, index) for index, rule in enumerate(rules)]


def normalize_review_rule(rule: dict[str, Any], index: int = 0) -> dict[str, Any]:
    enriched = dict(rule)
    topic = _review_topic(rule)
    item = _review_item(rule, topic)
    logic_types = _review_logic_types(rule)
    evidence_scope = _evidence_scope(rule)

    enriched["review_topic"] = topic
    enriched["review_item"] = item
    enriched["review_logic"] = [
        {"type": logic_type, "label": REVIEW_LOGIC_LABELS[logic_type]}
        for logic_type in logic_types
    ]
    enriched["evidence_scope"] = evidence_scope
    enriched["rule_execution"] = _rule_execution(rule, logic_types, evidence_scope)
    enriched["review_path"] = {
        "topic_id": topic["id"],
        "item_id": _stable_id("item", f"{topic['name']}|{item['name']}"),
        "rule_id": rule.get("rule_id") or _stable_id("rule", f"{index}|{rule.get('rule_name', '')}"),
    }
    return enriched


def build_review_rule_topics(
    rules: list[dict[str, Any]],
    review_items: list[dict[str, Any]] | None = None,
    configured_check_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build SCMC review topics for real item-by-item review."""
    enriched_rules = normalize_review_rules(rules)
    rules_by_id = {
        str(rule.get("rule_id")): rule
        for rule in enriched_rules
        if rule.get("rule_id")
    }
    topic_items: dict[str, list[dict[str, Any]]] = {
        spec["id"]: []
        for spec in SCMC_TOPIC_SPECS
    }
    rule_candidates_by_topic: dict[str, list[dict[str, Any]]] = {
        spec["id"]: []
        for spec in SCMC_TOPIC_SPECS
    }
    active_configured_topic_ids: set[str] = set()

    if configured_check_items is None:
        configured_check_items = []

    for check_item in configured_check_items:
        topic_id = str(check_item.get("topic_id") or "")
        if not topic_id:
            continue
        if check_item.get("enabled") is not False:
            active_configured_topic_ids.add(topic_id)
        topic_items.setdefault(topic_id, []).append(_configured_check_item_to_result(check_item))

    for rule in enriched_rules:
        topic_id = rule["review_path"]["topic_id"]
        rule_candidates_by_topic.setdefault(topic_id, []).append(_rule_to_check_item(rule))
        if topic_id not in active_configured_topic_ids:
            topic_items.setdefault(topic_id, []).append(_rule_to_check_item(rule))

    for review_item in review_items or []:
        issue_check_item = _issue_to_check_item(review_item, rules_by_id)
        topic_items.setdefault(issue_check_item["topic_id"], []).append(issue_check_item)

    result: list[dict[str, Any]] = []
    for index, spec in enumerate(SCMC_TOPIC_SPECS, start=1):
        has_active_configured_items = spec["id"] in active_configured_topic_ids
        check_items = _dedupe_check_items(topic_items.get(spec["id"], []))
        rule_candidates = _dedupe_check_items(rule_candidates_by_topic.get(spec["id"], []))
        if not has_active_configured_items:
            check_items = _pad_planned_check_items(spec, check_items)
        configured_check_item_count = sum(
            1 for item in check_items if item.get("ai_or_human_source") == "configured_checklist"
        )
        detected_error_count = sum(1 for item in check_items if item["status"] in {"failed", "issue"})
        check_status = _topic_status(check_items)
        result.append(
            {
                "id": spec["id"],
                "name": spec["name"],
                "sequence": index,
                "check_status": check_status,
                "check_item_count": spec["check_item_count"],
                "configured_check_item_count": configured_check_item_count,
                "error_item_count": spec["reference_error_count"],
                "detected_error_item_count": detected_error_count,
                "reference_error_count": spec["reference_error_count"],
                "main_review_types": spec["main_review_types"],
                "check_items": check_items,
                "rule_candidates": rule_candidates,
                # Backward-compatible aliases used by the existing frontend.
                "topic_id": spec["id"],
                "topic_name": spec["name"],
                "topic_category": "SCMC",
                "description": f"{spec['name']}逐项审查，覆盖{spec['check_item_count']}个核验点。",
                "items": [
                    {
                        "item_id": item["id"],
                        "item_name": item["review_sub_type"],
                        "logic_types": item.get("review_logic_types", []),
                        "rules": [item] if item.get("rule_id") else [],
                    }
                    for item in check_items
                ],
            }
        )
    return result


def execute_rule_precheck(
    rule: dict[str, Any],
    evidence: list[dict[str, Any]],
    structured_facts: list[dict[str, Any]] | None = None,
    cross_chapter_findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run deterministic, lightweight checks before LLM adjudication."""
    target_fields = [str(item) for item in rule.get("target_fields", []) if str(item).strip()]
    evidence_text = "\n".join(str(match.get("document", "")) for match in evidence)
    fact_text = "\n".join(
        str(fact.get("field_label") or fact.get("field_name") or "") + " " + str(fact.get("value") or "")
        for fact in (structured_facts or [])
    )
    haystack = f"{evidence_text}\n{fact_text}"
    matched = [field for field in target_fields if field and field in haystack]
    missing = [field for field in target_fields if field and field not in haystack]
    logic_types = [item["type"] for item in rule.get("review_logic", [])]
    scope = rule.get("evidence_scope", {})

    checks = [
        {
            "check_type": "target_field_presence",
            "logic_type": "content_review",
            "status": "pass" if not missing else "needs_review",
            "matched_fields": matched,
            "missing_fields": missing,
        },
        {
            "check_type": "evidence_scope_coverage",
            "logic_type": "format_review",
            "status": "pass" if evidence else "fail",
            "required_scope": scope,
            "matched_chunk_count": len(evidence),
        },
    ]
    if "consistency_review" in logic_types:
        checks.append(
            {
                "check_type": "cross_chapter_consistency",
                "logic_type": "consistency_review",
                "status": "needs_review" if cross_chapter_findings else "pass",
                "finding_count": len(cross_chapter_findings or []),
                "finding_ids": [finding.get("finding_id") for finding in (cross_chapter_findings or [])],
            }
        )
    if "table_calculation_review" in logic_types or "formula_calculation_review" in logic_types:
        checks.append(
            {
                "check_type": "calculation_traceability",
                "logic_type": "table_calculation_review",
                "status": "needs_review",
                "reason": "当前仅完成表格/公式证据定位，尚未执行结构化公式复算。",
            }
        )

    if not evidence:
        execution_status = "fail"
    elif missing and len(matched) == 0:
        execution_status = "potential_issue"
    elif missing:
        execution_status = "needs_review"
    else:
        execution_status = "pass"

    return {
        "execution_status": execution_status,
        "review_logic_types": logic_types,
        "matched_target_fields": matched,
        "missing_target_fields": missing,
        "checks": checks,
        "llm_required": True,
    }


def _review_topic(rule: dict[str, Any]) -> dict[str, str]:
    category = str(rule.get("category") or rule.get("rule_category") or "综合审查")
    spec = _scmc_topic_spec_for_text(_rule_text(rule), category)
    return {
        "id": spec["id"],
        "name": spec["name"],
        "category": category,
        "description": f"围绕 SCMC 主题“{spec['name']}”进行逐项证据定位、规则执行和问题输出。",
    }


def _review_item(rule: dict[str, Any], topic: dict[str, str]) -> dict[str, str]:
    name = str(rule.get("rule_name") or "未命名审查项")
    clean = re.sub(r"(审查|检查)$", "", name).strip(" ：:")
    return {
        "name": clean or name,
        "description": f"{topic['name']} / {clean or name}",
    }


def _review_logic_types(rule: dict[str, Any]) -> list[str]:
    text = _rule_text(rule)
    logic: list[str] = []
    if any(keyword in text for keyword in FORMAT_KEYWORDS):
        logic.append("format_review")
    if any(keyword in text for keyword in CONSISTENCY_KEYWORDS):
        logic.append("consistency_review")
    if any(keyword in text for keyword in TABLE_KEYWORDS):
        logic.append("table_calculation_review")
    if any(keyword in text for keyword in FORMULA_KEYWORDS):
        logic.append("formula_calculation_review")
    if any(keyword in text for keyword in BUSINESS_KEYWORDS):
        logic.append("business_logic_review")
    logic.append("content_review")
    return _dedupe(logic)


def _evidence_scope(rule: dict[str, Any]) -> dict[str, list[str]]:
    text = _rule_text(rule)
    chapters = [
        section
        for section, keywords in SECTION_SCOPE_RULES
        if any(keyword in text for keyword in keywords)
    ]
    if not chapters and rule.get("category"):
        chapters.append(str(rule["category"]))

    tables = []
    if any(keyword in text for keyword in TABLE_KEYWORDS):
        tables.append("相关统计表/计算表")
    if "土石方" in text or "表土" in text:
        tables.append("土石方平衡表/表土平衡表")
    if "投资" in text:
        tables.append("投资估算表")
    if "占地" in text or "面积" in text:
        tables.append("占地面积统计表")

    attachments = []
    if any(keyword in text for keyword in ["附件", "附图", "图件", "支撑材料", "立项文件", "主体设计文件", "批复"]):
        attachments.append("附件/附图/支撑材料")
    if any(keyword in text for keyword in ["立项文件", "主体设计文件", "审批手续", "批复"]):
        attachments.append("立项/主体设计/审批文件")

    regulations = [str(rule.get("rule_source", ""))] if rule.get("rule_source") else []
    return {
        "chapters": _dedupe(chapters),
        "tables": _dedupe(tables),
        "attachments": _dedupe(attachments),
        "regulations": regulations,
    }


def _rule_execution(rule: dict[str, Any], logic_types: list[str], evidence_scope: dict[str, list[str]]) -> dict[str, Any]:
    checks = []
    if "format_review" in logic_types:
        checks.append({"type": "scope_presence", "description": "核验证据范围内是否存在必备章节、表格、附件或支撑材料。"})
    if "content_review" in logic_types:
        checks.append({"type": "target_field_presence", "description": "核查目标字段是否在召回证据或结构化事实中明确出现。"})
    if "consistency_review" in logic_types:
        checks.append({"type": "cross_chapter_consistency", "description": "核查同一字段、同一指标在跨章节/跨表格中的口径一致性。"})
    if "table_calculation_review" in logic_types:
        checks.append({"type": "table_calculation_trace", "description": "定位相关统计表、平衡表或工程量表，供后续结构化复算。"})
    if "formula_calculation_review" in logic_types:
        checks.append({"type": "formula_trace", "description": "定位公式、指标、系数和计算结果，供后续公式复算。"})
    if "business_logic_review" in logic_types:
        checks.append({"type": "policy_logic", "description": "结合规则要求判断业务逻辑、合规性和措施闭环是否成立。"})

    return {
        "mode": "deterministic_precheck_then_llm_adjudication",
        "logic_types": logic_types,
        "evidence_scope": evidence_scope,
        "checks": checks,
        "issue_output": {
            "fields": ["risk_level", "issue_desc", "actual_value", "expected_value", "fix_suggestion", "evidence_nodes"],
            "requires_evidence": True,
        },
    }


def _scmc_topic_spec_for_text(text: str, category: str = "") -> dict[str, Any]:
    weighted_text = f"{text}\n{category}"
    rule_name = text.splitlines()[0] if text else ""
    best_spec = SCMC_TOPIC_SPECS[0]
    best_score = -1
    for spec in SCMC_TOPIC_SPECS:
        score = sum(1 for keyword in spec["keywords"] if keyword and keyword in weighted_text)
        if len(spec["name"]) >= 4 and spec["name"] in rule_name:
            score += 5
        if score > best_score:
            best_spec = spec
            best_score = score
    if best_score > 0:
        return best_spec

    category_fallbacks = {
        "投资估算与效益类": "scmc-001",
        "项目概况类": "scmc-003",
        "责任范围与目标类": "scmc-009",
        "分析预测类": "scmc-017",
        "措施布设类": "scmc-011",
        "监测类": "scmc-008",
        "区域特别要求": "scmc-014",
    }
    fallback_id = category_fallbacks.get(category)
    if fallback_id:
        return next(spec for spec in SCMC_TOPIC_SPECS if spec["id"] == fallback_id)
    return best_spec


def _rule_to_check_item(rule: dict[str, Any]) -> dict[str, Any]:
    logic = rule.get("review_logic", [])
    evidence_scope = rule.get("evidence_scope", {})
    topic_id = rule.get("review_path", {}).get("topic_id") or _review_topic(rule)["id"]
    rule_identity = str(rule.get("rule_id") or rule.get("review_path", {}).get("rule_id") or rule.get("rule_name", ""))
    review_criteria = rule.get("severity_policy") or rule.get("rule_description") or rule.get("evidence_requirement") or ""
    expected_result = rule.get("expected") or rule.get("evidence_requirement") or "证据满足规则要求，形成明确审查结论。"
    failure_conditions = [str(rule.get("severity_policy"))] if rule.get("severity_policy") else []
    source_rule_snapshot = {
        "rule_id": rule.get("rule_id"),
        "rule_name": rule.get("rule_name"),
        "rule_source": rule.get("rule_source"),
        "evidence_requirement": rule.get("evidence_requirement"),
        "severity_policy": rule.get("severity_policy"),
        "expected": rule.get("expected"),
        "review_logic": logic,
        "rule_execution": rule.get("rule_execution", {}),
    }
    return {
        "id": _stable_id("item", f"{topic_id}|{rule_identity}") if rule_identity else rule.get("review_path", {}).get("item_id") or _stable_id("check", str(rule.get("rule_name", ""))),
        "topic_id": topic_id,
        "rule_id": rule.get("rule_id"),
        "rule_name": rule.get("rule_name"),
        "review_type": logic[0]["label"] if logic else "内容审查",
        "review_sub_type": rule.get("review_item", {}).get("name") or rule.get("rule_name") or "未命名审查项",
        "review_logic": logic,
        "review_logic_types": [item.get("type") for item in logic if item.get("type")],
        "status": "pending",
        "conclusion": rule.get("evidence_requirement") or "待按规则逐条审查。",
        "evidence_texts": [],
        "evidence_locations": [],
        "regulation_clauses": [rule.get("rule_source")] if rule.get("rule_source") else [],
        "reasoning_process": rule.get("rule_execution", {}),
        "ai_or_human_source": "rule_set",
        "human_review_status": "pending",
        "evidence_scope": evidence_scope,
        "target_fields": rule.get("target_fields", []),
        "review_criteria": str(review_criteria),
        "expected_result": str(expected_result),
        "failure_conditions": failure_conditions,
        "source_rule_snapshot": source_rule_snapshot,
    }


def _configured_check_item_to_result(item: dict[str, Any]) -> dict[str, Any]:
    enabled = item.get("enabled") is not False
    executor_precheck = execute_check_item_precheck({**item, "enabled": enabled})
    default_status = executor_precheck.get("execution_status")
    if default_status == "pass":
        default_status = "pending"
    review_criteria = str(item.get("review_criteria") or "")
    expected_result = str(item.get("expected_result") or "")
    failure_conditions = item.get("failure_conditions") or []
    source_rule_snapshot = item.get("source_rule_snapshot") if isinstance(item.get("source_rule_snapshot"), dict) else {}
    return {
        "id": item.get("id"),
        "topic_id": item.get("topic_id"),
        "rule_id": item.get("rule_id", ""),
        "rule_name": item.get("rule_name", ""),
        "executor_type_id": item.get("executor_type_id", "manual_basic"),
        "review_type": item.get("review_type") or "人工基础核验",
        "review_sub_type": item.get("review_sub_type") or "未命名审查项",
        "review_logic": [
            {
                "type": item.get("executor_type_id", "manual_basic"),
                "label": item.get("review_type") or "人工基础核验",
            }
        ],
        "review_logic_types": [item.get("executor_type_id", "manual_basic")],
        "status": (item.get("status") or default_status or "pending") if enabled else "disabled",
        "conclusion": item.get("conclusion") or "待按配置执行审查。",
        "evidence_texts": [],
        "evidence_locations": [],
        "regulation_clauses": item.get("regulation_clauses") or [],
        "reasoning_process": {
            "executor_type_id": item.get("executor_type_id", "manual_basic"),
            "mode": "configurable_review_item",
            "configured": True,
            "executor_precheck": executor_precheck,
            "review_rule": {
                "criteria": review_criteria,
                "expected_result": expected_result,
                "failure_conditions": failure_conditions,
                "source_rule_snapshot": source_rule_snapshot,
            },
        },
        "ai_or_human_source": "configured_checklist",
        "human_review_status": "pending",
        "evidence_scope": item.get("evidence_scope") or {},
        "target_fields": item.get("target_fields") or [],
        "review_criteria": review_criteria,
        "expected_result": expected_result,
        "failure_conditions": failure_conditions,
        "source_rule_snapshot": source_rule_snapshot,
        "enabled": enabled,
    }


def _issue_to_check_item(issue: Any, rules_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    reasoning = _safe_json_loads(_issue_get(issue, "ai_reasoning", "{}"))
    rule_id = str(reasoning.get("rule_id") or "")
    rule = rules_by_id.get(rule_id)
    issue_text = "\n".join(
        str(part)
        for part in [
            _issue_get(issue, "risk_category", ""),
            _issue_get(issue, "ai_finding", ""),
            _issue_get(issue, "suggested_revision", ""),
            reasoning.get("rule_name", ""),
            reasoning.get("rule_description", ""),
            reasoning.get("actual_value", ""),
            reasoning.get("expected_value", ""),
        ]
    )
    topic_id = (
        rule.get("review_path", {}).get("topic_id")
        if rule
        else _scmc_topic_spec_for_text(issue_text, _issue_get(issue, "risk_category", ""))["id"]
    )
    logic = reasoning.get("review_logic") or (rule.get("review_logic", []) if rule else [])
    evidence_scope = reasoning.get("evidence_scope") or (rule.get("evidence_scope", {}) if rule else {})
    return {
        "id": _issue_get(issue, "id", _stable_id("issue", issue_text)),
        "topic_id": topic_id,
        "source_issue_id": _issue_get(issue, "id", ""),
        "rule_id": rule_id or (rule.get("rule_id") if rule else ""),
        "rule_name": reasoning.get("rule_name") or (rule.get("rule_name") if rule else ""),
        "review_type": logic[0].get("label") if logic else _issue_get(issue, "risk_category", "内容审查"),
        "review_sub_type": reasoning.get("rule_name") or (rule.get("review_item", {}).get("name") if rule else _issue_get(issue, "risk_category", "审查项")),
        "review_logic": logic,
        "review_logic_types": [item.get("type") for item in logic if item.get("type")],
        "status": _status_from_issue(issue),
        "conclusion": _issue_get(issue, "ai_finding", "") or "自动审查发现问题，待人工复核。",
        "evidence_texts": [_issue_get(issue, "clause_text", "")] if _issue_get(issue, "clause_text", "") else [],
        "evidence_locations": [_issue_location(issue)],
        "regulation_clauses": [reasoning.get("rule_source")] if reasoning.get("rule_source") else [],
        "reasoning_process": reasoning,
        "ai_or_human_source": _issue_source(issue),
        "human_review_status": _issue_get(issue, "human_decision", "pending"),
        "evidence_scope": evidence_scope,
        "target_fields": rule.get("target_fields", []) if rule else [],
        "risk_level": _issue_get(issue, "risk_level", ""),
        "confidence_score": _issue_get(issue, "confidence_score", None),
    }


def _status_from_issue(issue: Any) -> str:
    human_decision = str(_issue_get(issue, "human_decision", "pending"))
    if human_decision in {"reject", "rejected", "false_positive"} or bool(_issue_get(issue, "is_false_positive", False)):
        return "rejected"
    if human_decision in {"approve", "confirmed", "edit"}:
        return "failed"
    return "failed"


def _issue_source(issue: Any) -> str:
    human_decision = str(_issue_get(issue, "human_decision", "pending"))
    if human_decision and human_decision != "pending":
        return "human_reviewed"
    return _issue_get(issue, "source_type", "") or "ai"


def _issue_location(issue: Any) -> dict[str, Any]:
    return {
        "page_number": _issue_get(issue, "page_number", None),
        "paragraph_index": _issue_get(issue, "paragraph_index", None),
        "highlight_anchor": _issue_get(issue, "highlight_anchor", ""),
        "char_offset_start": _issue_get(issue, "char_offset_start", None),
        "char_offset_end": _issue_get(issue, "char_offset_end", None),
    }


def _pad_planned_check_items(spec: dict[str, Any], check_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    padded = list(check_items)
    participating_count = sum(1 for item in padded if item.get("status") != "disabled")
    start = participating_count + 1
    for number in range(start, spec["check_item_count"] + 1):
        padded.append(
            {
                "id": f"{spec['id']}-planned-{number:02d}",
                "topic_id": spec["id"],
                "rule_id": "",
                "rule_name": "",
                "review_type": spec["main_review_types"][0],
                "review_sub_type": f"{spec['name']}核验点 {number:02d}",
                "review_logic": [{"type": _logic_type_from_label(label), "label": label} for label in spec["main_review_types"]],
                "review_logic_types": [_logic_type_from_label(label) for label in spec["main_review_types"]],
                "status": "pending",
                "conclusion": "待结合章节、表格、附件和法规证据逐条核查。",
                "evidence_texts": [],
                "evidence_locations": [],
                "regulation_clauses": [],
                "reasoning_process": {},
                "ai_or_human_source": "planned_checklist",
                "human_review_status": "pending",
                "evidence_scope": {},
                "target_fields": [],
            }
        )
    return padded


def _dedupe_check_items(check_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for item in check_items:
        key = _check_item_dedupe_key(item)
        if key and key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _check_item_dedupe_key(item: dict[str, Any]) -> str:
    source = str(item.get("ai_or_human_source") or "")
    if source == "configured_checklist":
        return f"configured:{item.get('id') or item.get('rule_id') or item.get('review_sub_type')}"
    if item.get("source_issue_id"):
        return f"issue:{item.get('source_issue_id')}"
    if source in {"ai", "hybrid", "human_reviewed"}:
        return f"issue:{item.get('id') or item.get('rule_id') or item.get('review_sub_type')}"
    if source == "rule_set":
        return f"rule:{item.get('rule_id') or item.get('id')}"
    if source == "planned_checklist":
        return f"planned:{item.get('id')}"
    return f"{source or 'item'}:{item.get('id') or item.get('rule_id') or item.get('review_sub_type')}"


def _topic_status(check_items: list[dict[str, Any]]) -> str:
    statuses = {item.get("status") for item in check_items}
    if statuses & {"failed", "issue"}:
        return "failed"
    if statuses & {"needs_review", "pending"}:
        return "pending"
    return "passed"


def _logic_type_from_label(label: str) -> str:
    for logic_type, logic_label in REVIEW_LOGIC_LABELS.items():
        if logic_label == label:
            return logic_type
    return {
        "格式": "format_review",
        "内容": "content_review",
        "一致性": "consistency_review",
        "表内计算": "table_calculation_review",
        "公式": "formula_calculation_review",
        "公式计算": "formula_calculation_review",
        "业务逻辑": "business_logic_review",
    }.get(label, "content_review")


def _safe_json_loads(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(str(raw or "{}"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _issue_get(issue: Any, key: str, default: Any = None) -> Any:
    if isinstance(issue, dict):
        return issue.get(key, default)
    return getattr(issue, key, default)


def _topic_rule_summary(rule: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": rule.get("rule_id"),
        "rule_name": rule.get("rule_name"),
        "review_item_name": rule.get("review_item", {}).get("name"),
        "review_logic": rule.get("review_logic", []),
        "evidence_scope": rule.get("evidence_scope", {}),
        "rule_execution": rule.get("rule_execution", {}),
        "target_fields": rule.get("target_fields", []),
        "severity_policy": rule.get("severity_policy", ""),
        "evidence_requirement": rule.get("evidence_requirement", ""),
    }


def _rule_text(rule: dict[str, Any]) -> str:
    parts = [
        str(rule.get("rule_name", "")),
        str(rule.get("category", "")),
        str(rule.get("rule_source", "")),
        " ".join(str(item) for item in rule.get("target_fields", [])),
        str(rule.get("severity_policy", "")),
        str(rule.get("evidence_requirement", "")),
    ]
    return "\n".join(parts)


def _stable_id(prefix: str, value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{digest}"


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
