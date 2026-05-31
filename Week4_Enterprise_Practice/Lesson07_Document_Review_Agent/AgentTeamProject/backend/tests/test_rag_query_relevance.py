import json

import pytest

from app.services import rag_service
from app.services.water_review_service import ReviewChunk


def _chunk(chunk_id: str, text: str, section: str = "") -> ReviewChunk:
    index = int(chunk_id.rsplit("-", 1)[-1]) if "-" in chunk_id and chunk_id.rsplit("-", 1)[-1].isdigit() else 1
    return ReviewChunk(
        chunk_id=chunk_id,
        text=text,
        section=section,
        page_range=[index, index],
        bbox_list=[{"block_id": f"{chunk_id}-b1", "page": index, "bbox": [10, 20, 100, 40]}],
        table_refs=[],
        metadata={},
        char_start=0,
        char_end=len(text),
    )


class _FakeStore:
    def __init__(self, chunks: list[ReviewChunk], chunk_ids: list[str]) -> None:
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}
        self._chunk_ids = chunk_ids

    def query(self, query: str, top_k: int) -> list[dict]:
        matches = []
        for rank, chunk_id in enumerate(self._chunk_ids[:top_k], start=1):
            chunk = self._chunks[chunk_id]
            matches.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "rank": rank,
                    "vector_rank": rank,
                    "document": chunk.text,
                    "metadata": {
                        "chunk_id": chunk.chunk_id,
                        "chunk_index": rank - 1,
                        "page_start": chunk.page_range[0],
                        "page_end": chunk.page_range[-1],
                    },
                    "score": 0.7 - rank * 0.001,
                    "vector_score": 0.7 - rank * 0.001,
                    "retrieval_sources": ["vector"],
                    "source_ranks": {"vector": rank},
                }
            )
        return matches


class _QueryAwareStore:
    def __init__(self, chunks: list[ReviewChunk], query_matches: dict[str, list[str]]) -> None:
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}
        self._query_matches = query_matches

    def query(self, query: str, top_k: int) -> list[dict]:
        matches = []
        for rank, chunk_id in enumerate(self._query_matches.get(query, [])[:top_k], start=1):
            chunk = self._chunks[chunk_id]
            matches.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "rank": rank,
                    "vector_rank": rank,
                    "document": chunk.text,
                    "metadata": rag_service._chunk_metadata(chunk, rank - 1),
                    "score": 0.8 - rank * 0.001,
                    "vector_score": 0.8 - rank * 0.001,
                    "retrieval_sources": ["vector"],
                    "source_ranks": {"vector": rank},
                }
            )
        return matches


class _PassthroughReranker:
    def rerank(self, query: str, matches: list[dict], top_n: int) -> list[dict]:
        reranked = []
        for rank, match in enumerate(matches[:top_n], start=1):
            item = dict(match)
            item["rerank_rank"] = rank
            item["rerank_score"] = 1.0 / rank
            reranked.append(item)
        return reranked


def test_domain_query_filters_weak_heading_and_generic_distribution_matches():
    chunks = [
        _chunk("chunk-0001", "1 项目及项目区概况", "1 项目及项目区概况"),
        _chunk("chunk-0002", "项目区自来水管线分布及接水点见下图。", "2.2 自来水管线"),
        _chunk("chunk-0003", "本项目不存在弃渣（土、石）场。", "弃渣场设置分析"),
        _chunk("chunk-0004", "5.3 水土流失防治方案", "5.3 水土流失防治方案"),
        _chunk("chunk-0005", "防治区内水流排泄通畅，弃土弃渣得以拦挡，水土流失得到控制。", "防治措施"),
        _chunk("chunk-0006", "施工完成后清除表面渣土，进行场地土地整治。", "土地整治"),
        _chunk("chunk-0007", "外弃土方13.47万m3，开挖土方运至通州环球主题公园项目综合利用。", "土石方利用率"),
    ]
    store = _FakeStore(chunks, ["chunk-0001", "chunk-0004", "chunk-0006"])

    result = rag_service.retrieve_for_query(
        chunks,
        "弃渣场分布在哪",
        top_k=6,
        store=store,
        use_bm25=True,
        use_neighbors=True,
        use_rerank=False,
    )

    chunk_ids = [match["chunk_id"] for match in result["matches"]]
    assert "chunk-0003" in chunk_ids
    assert "chunk-0007" in chunk_ids
    assert "chunk-0001" not in chunk_ids
    assert "chunk-0002" not in chunk_ids
    assert "chunk-0004" not in chunk_ids
    assert "chunk-0005" not in chunk_ids
    assert "chunk-0006" not in chunk_ids


def test_retrieve_for_rules_aggregates_multiple_required_evidence_slots(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rag_service.settings, "siliconflow_reranker_model", "fake-reranker")
    monkeypatch.setattr(rag_service.settings, "rag_rerank_top_n", 3)
    monkeypatch.setattr(rag_service, "SiliconFlowRerankerProvider", lambda: _PassthroughReranker())
    chunks = [
        _chunk("chunk-0001", "本项目土石方挖方15.30万m3，填方5.275万m3。", "土石方平衡"),
        _chunk("chunk-0002", "本项目不存在弃渣（土、石）场。", "弃渣场设置分析"),
        _chunk("chunk-0003", "5.3 水土流失防治方案", "5.3 水土流失防治方案"),
    ]
    store = _QueryAwareStore(
        chunks,
        {
            "土石方 挖方 填方": ["chunk-0001"],
            "弃渣场 设置": ["chunk-0002"],
        },
    )
    rule = {
        "rule_id": "R-earthwork",
        "rule_name": "土石方与弃渣场一致性审查",
        "evidence_slots": [
            {
                "id": "earthwork_quantities",
                "label": "土石方数量",
                "required": True,
                "queries": ["土石方 挖方 填方"],
                "expected_terms": ["挖方", "填方"],
            },
            {
                "id": "spoil_site",
                "label": "弃渣场设置",
                "required": True,
                "queries": ["弃渣场 设置"],
                "expected_terms": ["弃渣"],
            },
        ],
    }

    retrieval = rag_service.retrieve_for_rules(store, chunks, [rule], top_k=2)[0]

    assert retrieval["missing_required_slot_ids"] == []
    assert [slot["status"] for slot in retrieval["slot_retrievals"]] == ["matched", "matched"]
    chunk_ids = [match["chunk_id"] for match in retrieval["matches"]]
    assert "chunk-0001" in chunk_ids
    assert "chunk-0002" in chunk_ids
    assert {"earthwork_quantities", "spoil_site"} == {
        slot_id for match in retrieval["matches"] for slot_id in match.get("evidence_slot_ids", [])
    }


def test_retrieve_for_rules_reports_missing_required_evidence_slot(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(rag_service.settings, "siliconflow_reranker_model", "fake-reranker")
    monkeypatch.setattr(rag_service, "SiliconFlowRerankerProvider", lambda: _PassthroughReranker())
    chunks = [
        _chunk("chunk-0001", "本项目土石方挖方15.30万m3，填方5.275万m3。", "土石方平衡"),
    ]
    store = _QueryAwareStore(chunks, {"土石方 挖方 填方": ["chunk-0001"], "弃渣场 设置": []})
    rule = {
        "rule_id": "R-missing-slot",
        "rule_name": "土石方与弃渣场一致性审查",
        "evidence_slots": [
            {"id": "earthwork_quantities", "required": True, "queries": ["土石方 挖方 填方"]},
            {"id": "spoil_site", "required": True, "queries": ["弃渣场 设置"]},
        ],
    }

    retrieval = rag_service.retrieve_for_rules(store, chunks, [rule], top_k=2)[0]

    assert retrieval["missing_required_slot_ids"] == ["spoil_site"]
    assert [slot["status"] for slot in retrieval["slot_retrievals"]] == ["matched", "missing"]


def test_adjudicate_top_rules_blocks_llm_when_required_slot_is_missing(monkeypatch: pytest.MonkeyPatch):
    def fail_llm(*args, **kwargs):
        raise AssertionError("LLM should not run when required evidence slot is missing")

    monkeypatch.setattr(rag_service, "_call_deepseek_adjudicator", fail_llm)
    match = {
        "chunk_id": "chunk-0001",
        "document": "本项目土石方挖方15.30万m3，填方5.275万m3。",
        "metadata": {
            "chunk_index": 0,
            "page_start": 20,
            "bbox_json": json.dumps([{"block_id": "p20-b1", "page": 20, "bbox": [1, 2, 3, 4]}], ensure_ascii=False),
            "block_ids_json": json.dumps(["p20-b1"], ensure_ascii=False),
        },
        "score": 0.8,
        "evidence_slot_ids": ["earthwork_quantities"],
        "slot_queries": ["土石方 挖方 填方"],
    }
    rule = {"rule_id": "R-missing-slot", "rule_name": "土石方与弃渣场一致性审查"}
    retrieval = {
        "rule_index": 0,
        "matches": [match],
        "missing_required_slot_ids": ["spoil_site"],
        "slot_retrievals": [
            {"slot_id": "earthwork_quantities", "status": "matched", "required": True},
            {"slot_id": "spoil_site", "status": "missing", "required": True},
        ],
        "candidate_score": 1,
    }

    issues = rag_service.adjudicate_top_rules("session", [], [rule], [retrieval], max_issues=1)

    assert len(issues) == 1
    issue = issues[0]
    reasoning = json.loads(issue["ai_reasoning"])
    assert issue["confidence_score"] == 0
    assert "缺失必填证据槽位：spoil_site" in issue["ai_finding"]
    assert reasoning["review_status"] == "needs_evidence"
    assert reasoning["conclusion_type"] == "needs_evidence"
    assert reasoning["rule_execution"]["result"]["llm_required"] is False


def test_adjudicate_top_rules_reports_missing_required_slot_even_without_matches(monkeypatch: pytest.MonkeyPatch):
    def fail_llm(*args, **kwargs):
        raise AssertionError("LLM should not run when there is no required-slot evidence")

    monkeypatch.setattr(rag_service, "_call_deepseek_adjudicator", fail_llm)
    rule = {"rule_id": "R-all-missing", "rule_name": "证据完整性审查"}
    retrieval = {
        "rule_index": 0,
        "matches": [],
        "missing_required_slot_ids": ["approval_or_design_content"],
        "slot_retrievals": [
            {"slot_id": "approval_or_design_content", "status": "missing", "required": True},
        ],
        "candidate_score": 1,
    }

    issues = rag_service.adjudicate_top_rules("session", [], [rule], [retrieval], max_issues=1)

    assert len(issues) == 1
    assert issues[0]["highlight_anchor"] == ""
    assert "缺失必填证据槽位：approval_or_design_content" in issues[0]["clause_text"]
    reasoning = json.loads(issues[0]["ai_reasoning"])
    assert reasoning["missing_required_slot_ids"] == ["approval_or_design_content"]
    assert reasoning["review_status"] == "needs_evidence"
