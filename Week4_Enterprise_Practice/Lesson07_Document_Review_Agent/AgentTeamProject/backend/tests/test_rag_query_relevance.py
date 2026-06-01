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


def test_adjudicate_top_rules_degrades_llm_timeout_and_short_circuits(monkeypatch: pytest.MonkeyPatch):
    calls = 0

    def fail_llm(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise rag_service.RAGReviewError("DeepSeek rule adjudication failed: Request timed out.")

    monkeypatch.setattr(rag_service, "_call_deepseek_adjudicator", fail_llm)
    match = {
        "chunk_id": "chunk-0001",
        "document": "本项目水土保持措施体系完整，但仍需人工复核。",
        "metadata": {
            "chunk_index": 0,
            "page_start": 12,
            "bbox_json": json.dumps([{"block_id": "p12-b1", "page": 12, "bbox": [1, 2, 3, 4]}], ensure_ascii=False),
            "block_ids_json": json.dumps(["p12-b1"], ensure_ascii=False),
        },
        "score": 0.8,
    }
    rules = [
        {"rule_id": "R-timeout-1", "rule_name": "规则判定超时 1", "severity_policy": "一般"},
        {"rule_id": "R-timeout-2", "rule_name": "规则判定超时 2", "severity_policy": "一般"},
    ]
    retrievals = [
        {"rule_index": 0, "matches": [match], "missing_required_slot_ids": [], "candidate_score": 2},
        {"rule_index": 1, "matches": [match], "missing_required_slot_ids": [], "candidate_score": 1},
    ]

    issues = rag_service.adjudicate_top_rules("session", [], rules, retrievals, max_issues=2)

    assert calls == 1
    assert len(issues) == 2
    assert all("规则审查模型判定失败" in issue["ai_finding"] for issue in issues)
    reasonings = [json.loads(issue["ai_reasoning"]) for issue in issues]
    assert all(reasoning["review_status"] == "needs_review" for reasoning in reasonings)
    assert all(reasoning["conclusion_type"] == "needs_review" for reasoning in reasonings)
    assert reasonings[0]["llm_error"]["short_circuited"] is False
    assert reasonings[1]["llm_error"]["short_circuited"] is True


def test_run_rag_review_reuses_cached_retrievals_and_issues_without_vector_service(tmp_path, monkeypatch: pytest.MonkeyPatch):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    session_id = "cached-rag-session"
    chunks = [_chunk("chunk-0001", "项目名称：缓存项目。", "综合说明")]
    rules = [{"rule_id": "R-cache", "rule_name": "缓存规则"}]
    retrievals = [
        {
            "rule_index": 0,
            "rule_id": "R-cache",
            "rule_name": "缓存规则",
            "matches": [{"chunk_id": "chunk-0001", "document": "项目名称：缓存项目。"}],
            "candidate_score": 1,
        }
    ]
    issues = [
        {
            "id": "issue-cache",
            "session_id": session_id,
            "rule_id": "R-cache",
            "ai_finding": "缓存命中",
        }
    ]
    manifest = {
        "session_id": session_id,
        "vector_store": str(tmp_path / "vectors"),
        "collection": "water_review_cached",
        "chunk_count": 1,
        "rule_count": 1,
        "embedding_model": rag_service.settings.siliconflow_embedding_model,
        "embedding_dimensions": rag_service.settings.siliconflow_embedding_dimensions,
        "retrieval_enrichment_version": rag_service.RETRIEVAL_ENRICHMENT_VERSION,
        "reranker_model": rag_service.settings.siliconflow_reranker_model,
        "retrieval_top_k": rag_service.settings.rag_top_k,
        "rerank_top_n": rag_service.settings.rag_rerank_top_n,
    }
    (artifact_dir / "rag_index_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (artifact_dir / "rag_retrievals.json").write_text(json.dumps(retrievals, ensure_ascii=False), encoding="utf-8")
    (artifact_dir / "rag_issues.json").write_text(json.dumps(issues, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(rag_service.settings, "siliconflow_api_key", "")
    monkeypatch.setattr(rag_service, "ChromaChunkStore", lambda *_args, **_kwargs: pytest.fail("vector store should use cache"))
    monkeypatch.setattr(rag_service, "retrieve_for_rules", lambda *_args, **_kwargs: pytest.fail("retrieval should use cache"))
    monkeypatch.setattr(rag_service, "adjudicate_top_rules", lambda *_args, **_kwargs: pytest.fail("issues should use cache"))

    result = rag_service.run_rag_review(session_id, chunks, rules, artifact_dir)

    assert result["retrievals"] == retrievals
    assert result["issues"] == issues
    assert result["cache_hits"] == {"rag_retrievals": True, "rag_issues": True}
