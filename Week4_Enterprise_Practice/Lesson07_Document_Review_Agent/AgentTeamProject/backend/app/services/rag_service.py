"""RAG retrieval and rule adjudication for water review.

The service is intentionally framework-light: embeddings are generated through
SiliconFlow, vectors are persisted in local Chroma, and DeepSeek turns retrieved
evidence into ReviewItem-compatible issue dicts.
"""

from __future__ import annotations

import json
import hashlib
import math
import re
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import httpx

from app.config import get_llm, settings
from app.services.review_retrieval_defaults import EVIDENCE_SLOT_RETRIEVAL_DEFAULTS
from app.services.review_rule_schema import execute_rule_precheck


class RAGReviewError(RuntimeError):
    """Raised when the RAG path cannot complete safely."""


RETRIEVAL_ENRICHMENT_VERSION = "v4"
MAX_RULE_EVIDENCE_SLOTS = 8
MAX_RULE_EVIDENCE_SLOT_QUERIES = 3
MAX_RULE_EVIDENCE_SLOT_QUERY_LENGTH = 240


def _post_json_with_retries(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int,
    label: str,
    attempts: int = 3,
) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = httpx.post(url, headers=headers, json=payload, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            last_exc = exc
            if attempt < attempts and _is_retryable_http_error(exc):
                wait_seconds = 2 ** (attempt - 1)
                print(f"[rag] retry {label} {attempt + 1}/{attempts}: {exc}", flush=True)
                time.sleep(wait_seconds)
                continue
            raise RAGReviewError(f"SiliconFlow {label} request failed: {exc}") from exc
    raise RAGReviewError(f"SiliconFlow {label} request failed: {last_exc}")


def _is_retryable_http_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {408, 429, 500, 502, 503, 504}
    return isinstance(
        exc,
        (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.ProxyError,
            httpx.RemoteProtocolError,
            httpx.NetworkError,
        ),
    )


def run_rag_review(
    session_id: str,
    chunks: list[Any],
    rules: list[dict[str, Any]],
    artifact_dir: Path,
    facts: list[dict[str, Any]] | None = None,
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not settings.siliconflow_api_key:
        raise RAGReviewError("SILICONFLOW_API_KEY is required for RAG review")

    artifact_dir.mkdir(parents=True, exist_ok=True)
    vector_dir = Path(settings.storage_path) / "vector_stores" / "water_review" / session_id
    vector_dir.mkdir(parents=True, exist_ok=True)

    embedder = SiliconFlowEmbeddingProvider()
    store = ChromaChunkStore(vector_dir, session_id, embedder)
    vector_started = time.perf_counter()
    store.rebuild(chunks)
    vector_rebuild_duration_ms = int((time.perf_counter() - vector_started) * 1000)

    project_type = _infer_project_type(chunks)
    applicable_rules = _filter_applicable_rules(project_type, rules)
    structured_facts = facts or []
    cross_chapter_findings = findings or []
    retrievals = retrieve_for_rules(
        store,
        chunks,
        applicable_rules,
        top_k=settings.rag_top_k,
        facts=structured_facts,
        findings=cross_chapter_findings,
    )
    index_manifest = {
        "session_id": session_id,
        "vector_store": str(vector_dir),
        "collection": store.collection_name,
        "chunk_count": len(chunks),
        "rule_count": len(rules),
        "project_type": project_type,
        "applicable_rule_count": len(applicable_rules),
        "review_topic_count": len({rule.get("review_path", {}).get("topic_id") for rule in applicable_rules if rule.get("review_path")}),
        "review_logic_types": sorted(
            {
                logic.get("type")
                for rule in applicable_rules
                for logic in rule.get("review_logic", [])
                if logic.get("type")
            }
        ),
        "embedding_model": settings.siliconflow_embedding_model,
        "embedding_dimensions": settings.siliconflow_embedding_dimensions,
        "retrieval_enrichment_version": RETRIEVAL_ENRICHMENT_VERSION,
        "reranker_model": settings.siliconflow_reranker_model,
        "retrieval_top_k": settings.rag_top_k,
        "rerank_top_n": settings.rag_rerank_top_n,
        "langextract_fact_count": len(structured_facts),
        "cross_chapter_finding_count": len(cross_chapter_findings),
        "vector_rebuild_duration_ms": vector_rebuild_duration_ms,
        "vector_total_duration_ms": vector_rebuild_duration_ms,
    }

    _write_json(artifact_dir / "rag_index_manifest.json", index_manifest)
    _write_json(artifact_dir / "rag_retrievals.json", retrievals)

    issues = adjudicate_top_rules(
        session_id,
        chunks,
        applicable_rules,
        retrievals,
        max_issues=settings.rag_max_issues,
    )
    _write_json(artifact_dir / "rag_issues.json", issues)

    return {
        "issues": issues,
        "retrievals": retrievals,
        "index_manifest": index_manifest,
    }


def _infer_project_type(chunks: list[Any]) -> str:
    text = "\n".join(_chunk_text(chunk) for chunk in chunks[:80])
    if any(keyword in text for keyword in ["图书馆", "校区", "学校", "教学楼", "科研楼", "房屋建筑"]):
        return "生产建设项目"
    project_type_keywords = [
        ("铁路建设项目", ["铁路工程", "铁路建设", "铁路线路", "轨道交通", "线路路基"]),
        ("公路建设项目", ["高速公路", "公路工程", "公路建设", "互通立交", "路线方案", "路基工程"]),
        ("水利建设项目", ["水库", "水闸", "灌区", "堤防", "泵站"]),
        ("水电建设项目", ["水电站", "水电枢纽", "大坝"]),
        ("管道建设项目", ["输油管道", "输气管道", "管道工程", "管沟"]),
        ("核电建设项目", ["核电", "核岛", "厂址"]),
        ("煤炭建设项目", ["煤矿", "露天矿", "排矸场", "采煤", "矿井"]),
        ("输变电建设项目", ["输变电", "变电站", "塔基", "输电线路"]),
    ]
    for project_type, keywords in project_type_keywords:
        if any(keyword in text for keyword in keywords):
            return project_type
    return "生产建设项目"


def _filter_applicable_rules(project_type: str, rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    applicable: list[dict[str, Any]] = []
    for rule in rules:
        project_types = [str(item) for item in rule.get("applicable_project_type", []) if str(item).strip()]
        if not project_types or "生产建设项目" in project_types or project_type in project_types:
            applicable.append(rule)
    return applicable or rules


class SiliconFlowEmbeddingProvider:
    def __init__(self) -> None:
        self.api_key = settings.siliconflow_api_key
        self.base_url = settings.siliconflow_base_url.rstrip("/")
        self.model = settings.siliconflow_embedding_model
        self.dimensions = settings.siliconflow_embedding_dimensions

    def embed_texts(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            payload: dict[str, Any] = {
                "model": self.model,
                "input": batch,
                "encoding_format": "float",
            }
            if self.dimensions:
                payload["dimensions"] = self.dimensions
            try:
                data = _post_json_with_retries(
                    f"{self.base_url}/embeddings",
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    payload=payload,
                    timeout=60,
                    label="embedding",
                )
            except Exception as exc:
                raise RAGReviewError(str(exc)) from exc

            try:
                ordered = sorted(data["data"], key=lambda item: item.get("index", 0))
                embeddings.extend([item["embedding"] for item in ordered])
            except Exception as exc:
                raise RAGReviewError("SiliconFlow embedding response shape is invalid") from exc
        return embeddings


class SiliconFlowRerankerProvider:
    def __init__(self) -> None:
        self.api_key = settings.siliconflow_api_key
        self.base_url = settings.siliconflow_base_url.rstrip("/")
        self.model = settings.siliconflow_reranker_model
        self.instruction = settings.siliconflow_reranker_instruction

    def rerank(self, query: str, matches: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
        if not self.model or not matches:
            return matches[:top_n]

        documents = [str(match.get("document", "")) for match in matches]
        payload: dict[str, Any] = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": min(top_n, len(documents)),
            "return_documents": False,
        }
        if self.instruction and "Qwen3-Reranker" in self.model:
            payload["instruction"] = self.instruction
        try:
            data = _post_json_with_retries(
                f"{self.base_url}/rerank",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                payload=payload,
                timeout=90,
                label="reranker",
            )
        except Exception as exc:
            raise RAGReviewError(str(exc)) from exc

        ranked: list[dict[str, Any]] = []
        seen: set[int] = set()
        try:
            results = data.get("results", [])
            for rank, result in enumerate(results, start=1):
                index = int(result["index"])
                if index in seen or index < 0 or index >= len(matches):
                    continue
                seen.add(index)
                item = dict(matches[index])
                item["rerank_rank"] = rank
                item["rerank_score"] = float(result.get("relevance_score", 0))
                _add_retrieval_source(item, "rerank", rank)
                ranked.append(item)
        except Exception as exc:
            raise RAGReviewError("SiliconFlow reranker response shape is invalid") from exc

        if len(ranked) < top_n:
            ranked_ids = {item.get("chunk_id") for item in ranked}
            ranked.extend(match for match in matches if match.get("chunk_id") not in ranked_ids)
        return ranked[:top_n]


class ChromaChunkStore:
    def __init__(self, persist_dir: Path, session_id: str, embedder: SiliconFlowEmbeddingProvider) -> None:
        import chromadb

        self.client = chromadb.PersistentClient(path=str(persist_dir))
        safe_session = re.sub(r"[^a-zA-Z0-9_-]", "_", session_id)
        signature = hashlib.sha1(
            (
                f"{settings.siliconflow_embedding_model}:"
                f"{settings.siliconflow_embedding_dimensions}:"
                f"{RETRIEVAL_ENRICHMENT_VERSION}"
            ).encode()
        ).hexdigest()[:8]
        self.collection_name = f"water_review_{safe_session}_{signature}"
        self._delete_stale_session_collections(safe_session)
        self.collection = self._create_collection()
        self.embedder = embedder

    def _delete_stale_session_collections(self, safe_session: str) -> None:
        prefix = f"water_review_{safe_session}_"
        try:
            collections = self.client.list_collections()
        except Exception:
            return
        for collection in collections:
            name = collection if isinstance(collection, str) else getattr(collection, "name", "")
            if name.startswith(prefix) and name != self.collection_name:
                self.client.delete_collection(name)

    def _create_collection(self) -> Any:
        return self.client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def rebuild(self, chunks: list[Any]) -> None:
        chunk_ids = [_chunk_id(chunk) for chunk in chunks]
        index_content_hash = _index_content_hash(chunks)
        existing = self.collection.get(include=["metadatas"])
        ids = existing.get("ids", [])
        existing_metadatas = existing.get("metadatas") or []
        existing_dimension = self._existing_embedding_dimension()
        if (
            set(ids) == set(chunk_ids)
            and existing_dimension == settings.siliconflow_embedding_dimensions
            and _existing_index_hash_matches(existing_metadatas, index_content_hash)
        ):
            return
        if ids and existing_dimension != settings.siliconflow_embedding_dimensions:
            self.client.delete_collection(self.collection_name)
            self.collection = self._create_collection()
            ids = []
        if ids:
            self.collection.delete(ids=ids)

        documents = [_chunk_text(chunk) for chunk in chunks]
        embedding_documents = [_chunk_embedding_text(chunk) for chunk in chunks]
        embeddings = self.embedder.embed_texts(embedding_documents)
        self.collection.upsert(
            ids=chunk_ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=[
                _chunk_metadata(chunk, index, index_content_hash=index_content_hash)
                for index, chunk in enumerate(chunks)
            ],
        )

    def _existing_embedding_dimension(self) -> int | None:
        try:
            probe = self.collection.get(limit=1, include=["embeddings"])
            embeddings = probe.get("embeddings")
            if embeddings is None:
                return None
            if len(embeddings) == 0:
                return None
            return len(embeddings[0])
        except Exception:
            return None

    def query(self, query: str, top_k: int) -> list[dict[str, Any]]:
        embedding = self.embedder.embed_texts([query])[0]
        return self.query_by_embedding(embedding, top_k)

    def query_by_embedding(self, embedding: list[float], top_k: int) -> list[dict[str, Any]]:
        result = self.collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        matches: list[dict[str, Any]] = []
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        for rank, chunk_id in enumerate(ids, start=1):
            score = 1.0 / (1.0 + float(distances[rank - 1]))
            matches.append(
                {
                    "chunk_id": chunk_id,
                    "rank": rank,
                    "vector_rank": rank,
                    "document": docs[rank - 1],
                    "metadata": metadatas[rank - 1],
                    "distance": distances[rank - 1],
                    "score": score,
                    "vector_score": score,
                    "retrieval_sources": ["vector"],
                    "source_ranks": {"vector": rank},
                }
            )
        return matches


def retrieve_for_rules(
    store: ChromaChunkStore,
    chunks: list[Any],
    rules: list[dict[str, Any]],
    top_k: int,
    facts: list[dict[str, Any]] | None = None,
    findings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    bm25 = BM25Index(chunks)
    reranker = SiliconFlowRerankerProvider()
    by_id = {_chunk_id(chunk): chunk for chunk in chunks}
    by_index = {_chunk_id(chunk): index for index, chunk in enumerate(chunks)}

    retrievals: list[dict[str, Any]] = []
    for rule_index, rule in enumerate(rules):
        query = _rule_query(rule)
        matched_facts = _facts_for_rule(rule, facts or [])
        matched_findings = _findings_for_rule(rule, findings or [], matched_facts)
        slot_retrievals = _retrieve_rule_evidence_slots(
            rule,
            store,
            bm25,
            chunks,
            by_id,
            by_index,
            reranker,
            top_k=top_k,
        )
        if slot_retrievals:
            reranked = _merge_rule_slot_matches(
                slot_retrievals,
                limit=max(top_k, settings.rag_rerank_top_n, len(slot_retrievals) * EVIDENCE_SLOT_RETRIEVAL_DEFAULTS.final_top_k_per_slot),
            )
            missing_required_slot_ids = [
                slot["slot_id"]
                for slot in slot_retrievals
                if slot.get("required") is True and slot.get("status") != "matched"
            ]
        else:
            reranked = _retrieve_rule_query_matches(
                query,
                store,
                bm25,
                chunks,
                by_id,
                by_index,
                reranker,
                top_k=top_k,
                rerank_top_n=settings.rag_rerank_top_n,
            )
            missing_required_slot_ids = []
        retrievals.append(
            {
                "rule_index": rule_index,
                "rule_id": rule.get("rule_id", f"rule-{rule_index}"),
                "rule_name": rule.get("rule_name", ""),
                "review_topic": rule.get("review_topic", {}),
                "review_item": rule.get("review_item", {}),
                "review_logic": rule.get("review_logic", []),
                "evidence_scope": rule.get("evidence_scope", {}),
                "rule_execution": rule.get("rule_execution", {}),
                "query": query,
                "matches": reranked,
                "slot_retrievals": slot_retrievals,
                "missing_required_slot_ids": missing_required_slot_ids,
                "structured_facts": [_compact_fact(fact) for fact in matched_facts[:12]],
                "cross_chapter_findings": [_compact_finding(finding) for finding in matched_findings[:6]],
                "fact_ids": [fact.get("fact_id") for fact in matched_facts[:12] if fact.get("fact_id")],
                "finding_ids": [finding.get("finding_id") for finding in matched_findings[:6] if finding.get("finding_id")],
                "candidate_score": _candidate_score(rule, reranked, matched_facts, matched_findings),
            }
        )
    return retrievals


def _retrieve_rule_evidence_slots(
    rule: dict[str, Any],
    store: ChromaChunkStore,
    bm25: "BM25Index",
    chunks: list[Any],
    by_id: dict[str, Any],
    by_index: dict[str, int],
    reranker: "SiliconFlowRerankerProvider",
    top_k: int,
) -> list[dict[str, Any]]:
    raw_slots = [slot for slot in rule.get("evidence_slots", []) if isinstance(slot, dict)]
    if not raw_slots:
        return []

    slot_retrievals: list[dict[str, Any]] = []
    for slot in raw_slots[:MAX_RULE_EVIDENCE_SLOTS]:
        slot_id = _slot_id(slot)
        label = str(slot.get("label") or slot_id)
        queries = _slot_queries(slot)[:MAX_RULE_EVIDENCE_SLOT_QUERIES]
        query_results: list[dict[str, Any]] = []
        by_chunk_id: dict[str, dict[str, Any]] = {}
        for query in queries:
            matches = _retrieve_rule_query_matches(
                query,
                store,
                bm25,
                chunks,
                by_id,
                by_index,
                reranker,
                top_k=max(top_k, EVIDENCE_SLOT_RETRIEVAL_DEFAULTS.candidate_top_k),
                rerank_top_n=EVIDENCE_SLOT_RETRIEVAL_DEFAULTS.rerank_candidate_top_n,
            )
            tagged_matches = [
                _tag_slot_match(match, slot_id, label, query, rank)
                for rank, match in enumerate(matches, start=1)
            ]
            for match in tagged_matches:
                chunk_id = str(match.get("chunk_id") or "")
                if chunk_id and chunk_id not in by_chunk_id:
                    by_chunk_id[chunk_id] = match
            query_results.append(
                {
                    "query": query,
                    "match_count": len(tagged_matches),
                    "matches": tagged_matches[: EVIDENCE_SLOT_RETRIEVAL_DEFAULTS.prompt_match_limit],
                }
            )

        matches = list(by_chunk_id.values())[: EVIDENCE_SLOT_RETRIEVAL_DEFAULTS.final_top_k_per_slot]
        expected_terms = _string_list(slot.get("expected_terms"))
        haystack = "\n".join(_match_evidence_text(match) for match in matches)
        matched_terms = [term for term in expected_terms if term in haystack]
        missing_terms = [term for term in expected_terms if term not in matched_terms]
        min_matches = _positive_int(slot.get("min_matches"), EVIDENCE_SLOT_RETRIEVAL_DEFAULTS.min_matches)
        if not queries:
            status = "not_configured"
        elif len(matches) >= min_matches and not missing_terms:
            status = "matched"
        else:
            status = "missing"
        slot_retrievals.append(
            {
                "slot_id": slot_id,
                "label": label,
                "required": slot.get("required") is True,
                "status": status,
                "min_matches": min_matches,
                "queries": query_results,
                "query_count": len(query_results),
                "query_limit": MAX_RULE_EVIDENCE_SLOT_QUERIES,
                "truncated_queries": len(_slot_queries(slot)) > len(queries),
                "matches": matches,
                "match_count": len(matches),
                "expected_terms": expected_terms,
                "matched_expected_terms": matched_terms,
                "missing_expected_terms": missing_terms,
            }
        )
    return slot_retrievals


def _retrieve_rule_query_matches(
    query: str,
    store: ChromaChunkStore,
    bm25: "BM25Index",
    chunks: list[Any],
    by_id: dict[str, Any],
    by_index: dict[str, int],
    reranker: "SiliconFlowRerankerProvider",
    top_k: int,
    rerank_top_n: int,
) -> list[dict[str, Any]]:
    vector_matches = store.query(query, top_k=top_k)
    bm25_matches = bm25.query(query, top_k=top_k)
    focus_terms = _domain_query_focus_terms(query)
    if focus_terms and _matches_contain_focus_terms([*vector_matches, *bm25_matches], focus_terms):
        vector_matches = _filter_matches_by_focus_terms(vector_matches, focus_terms)
        bm25_matches = _filter_matches_by_focus_terms(bm25_matches, focus_terms)
    fused = _rrf(vector_matches, bm25_matches) if vector_matches and bm25_matches else (vector_matches or bm25_matches)
    expanded = _expand_neighbors(
        fused[:top_k],
        chunks,
        by_id,
        by_index,
        limit=max(rerank_top_n * 2, rerank_top_n),
    )
    if focus_terms:
        expanded = _filter_matches_by_focus_terms(expanded, focus_terms)
        expanded = _filter_matches_by_location_intent(query, expanded)
    if settings.siliconflow_reranker_model:
        matches = reranker.rerank(query, expanded, top_n=rerank_top_n)
    else:
        matches = expanded[:rerank_top_n]
    if focus_terms:
        matches = _filter_matches_by_focus_terms(matches, focus_terms)
        matches = _filter_matches_by_location_intent(query, matches)
    return _with_final_ranks(matches)


def _tag_slot_match(
    match: dict[str, Any],
    slot_id: str,
    label: str,
    query: str,
    rank: int,
) -> dict[str, Any]:
    item = dict(match)
    item["evidence_slot_id"] = slot_id
    item["evidence_slot_label"] = label
    item["slot_query"] = query
    item["evidence_slot_ids"] = [slot_id]
    item["evidence_slot_labels"] = [label]
    item["slot_queries"] = [query]
    _add_retrieval_source(item, f"slot:{slot_id}", rank)
    return item


def _merge_rule_slot_matches(slot_retrievals: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    by_chunk_id: dict[str, dict[str, Any]] = {}
    ordered: list[dict[str, Any]] = []
    max_match_count = max((len(slot.get("matches", [])) for slot in slot_retrievals), default=0)
    for match_index in range(max_match_count):
        for slot in slot_retrievals:
            matches = slot.get("matches", [])
            if not isinstance(matches, list) or match_index >= len(matches):
                continue
            match = matches[match_index]
            chunk_id = str(match.get("chunk_id") or "")
            if not chunk_id:
                continue
            if chunk_id not in by_chunk_id:
                item = dict(match)
                by_chunk_id[chunk_id] = item
                ordered.append(item)
                continue
            _merge_slot_match(by_chunk_id[chunk_id], match)
    return _with_final_ranks(ordered[:limit])


def _merge_slot_match(target: dict[str, Any], source: dict[str, Any]) -> None:
    target["score"] = max(float(target.get("score") or 0), float(source.get("score") or 0))
    for key in ("vector_score", "bm25_score", "rerank_score"):
        if source.get(key) is None:
            continue
        if target.get(key) is None or float(source.get(key) or 0) > float(target.get(key) or 0):
            target[key] = source.get(key)
    for key in ("evidence_slot_ids", "evidence_slot_labels", "slot_queries"):
        current = [str(item) for item in target.get(key, []) if str(item)]
        incoming = [str(item) for item in source.get(key, []) if str(item)]
        target[key] = list(dict.fromkeys([*current, *incoming]))
    _merge_retrieval_sources(target, source)


def _slot_queries(slot: dict[str, Any]) -> list[str]:
    queries: list[str] = []
    for query in _string_list(slot.get("queries")):
        trimmed = query[:MAX_RULE_EVIDENCE_SLOT_QUERY_LENGTH].strip()
        if trimmed:
            queries.append(trimmed)
    return queries


def _slot_id(slot: dict[str, Any]) -> str:
    return str(slot.get("id") or slot.get("slot_id") or "").strip() or "unnamed_slot"


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def retrieve_for_query(
    chunks: list[Any],
    query: str,
    top_k: int,
    store: ChromaChunkStore | None = None,
    use_bm25: bool = True,
    use_neighbors: bool = True,
    use_rerank: bool = True,
    rerank_top_n: int | None = None,
) -> dict[str, Any]:
    bm25 = BM25Index(chunks) if use_bm25 else None
    effective_rerank_top_n = _positive_int(rerank_top_n, settings.rag_rerank_top_n)
    by_id = {_chunk_id(chunk): chunk for chunk in chunks}
    by_index = {_chunk_id(chunk): index for index, chunk in enumerate(chunks)}
    vector_matches: list[dict[str, Any]] = []
    vector_available = store is not None
    if store is not None:
        try:
            vector_matches = store.query(query, top_k=top_k)
        except Exception as exc:
            raise RAGReviewError(f"vector retrieval failed: {exc}") from exc

    bm25_matches = bm25.query(query, top_k=top_k) if bm25 else []
    focus_terms = _domain_query_focus_terms(query)
    if focus_terms and _matches_contain_focus_terms([*vector_matches, *bm25_matches], focus_terms):
        vector_matches = _filter_matches_by_focus_terms(vector_matches, focus_terms)
        bm25_matches = _filter_matches_by_focus_terms(bm25_matches, focus_terms)
    if vector_matches and bm25_matches:
        fused = _rrf(vector_matches, bm25_matches)
    elif vector_matches:
        fused = vector_matches
    else:
        fused = bm25_matches
    if use_neighbors:
        expanded = _expand_neighbors(
            fused[:top_k],
            chunks,
            by_id,
            by_index,
            limit=max(top_k, effective_rerank_top_n),
        )
    else:
        expanded = fused[:top_k]
    if focus_terms:
        expanded = _filter_matches_by_focus_terms(expanded, focus_terms)
        expanded = _filter_matches_by_location_intent(query, expanded)
    rerank_available = bool(vector_available and use_rerank and settings.siliconflow_reranker_model)
    if rerank_available:
        matches = SiliconFlowRerankerProvider().rerank(query, expanded, top_n=min(top_k, effective_rerank_top_n))
    else:
        matches = expanded[:top_k]
    if focus_terms:
        matches = _filter_matches_by_focus_terms(matches, focus_terms)
        matches = _filter_matches_by_location_intent(query, matches)
    matches = _with_final_ranks(matches)
    return {
        "query": query,
        "matches": matches,
        "vector_available": vector_available,
        "bm25_available": use_bm25,
        "rerank_available": rerank_available,
        "retrieval_mode": _retrieval_mode(vector_available, use_bm25, use_neighbors, rerank_available),
    }


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


_DOMAIN_QUERY_FOCUS_GROUPS: tuple[tuple[str, ...], ...] = (
    ("弃渣场", "弃渣", "弃土", "弃方", "弃土场", "弃石", "排矸"),
    ("取土场", "取土", "取料场", "取料", "采石场", "借土"),
)
_LOCATION_QUERY_TERMS = ("在哪", "哪里", "何处", "分布", "位置", "去向", "场址")
_LOCATION_EVIDENCE_TERMS = ("不存在", "不在", "不布设", "未布设", "布设", "设置", "运至", "去向", "调配", "综合利用", "场址", "位置")


def _domain_query_focus_terms(query: str) -> list[str]:
    normalized = query.replace("（", "").replace("）", "").replace("(", "").replace(")", "")
    terms: list[str] = []
    for group in _DOMAIN_QUERY_FOCUS_GROUPS:
        if any(term in normalized for term in group):
            terms.extend(group)
    return list(dict.fromkeys(terms))


def _matches_contain_focus_terms(matches: list[dict[str, Any]], focus_terms: list[str]) -> bool:
    return any(_match_contains_focus_term(match, focus_terms) for match in matches)


def _filter_matches_by_focus_terms(matches: list[dict[str, Any]], focus_terms: list[str]) -> list[dict[str, Any]]:
    if not matches or not focus_terms:
        return matches
    filtered = [match for match in matches if _match_contains_focus_term(match, focus_terms)]
    return filtered or matches


def _filter_matches_by_location_intent(query: str, matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not matches or not any(term in query for term in _LOCATION_QUERY_TERMS):
        return matches
    filtered = [match for match in matches if _match_contains_any_term(match, _LOCATION_EVIDENCE_TERMS)]
    return filtered or matches


def _match_contains_focus_term(match: dict[str, Any], focus_terms: list[str]) -> bool:
    return _match_contains_any_term(match, focus_terms)


def _match_contains_any_term(match: dict[str, Any], terms: tuple[str, ...] | list[str]) -> bool:
    metadata = match.get("metadata") if isinstance(match.get("metadata"), dict) else {}
    haystack = "\n".join(
        [
            str(match.get("document") or ""),
            str(metadata.get("section") or ""),
            str(metadata.get("evidence_window_text") or ""),
        ]
    )
    return any(term and term in haystack for term in terms)


class BM25Index:
    def __init__(self, chunks: list[Any]) -> None:
        self.chunks = chunks
        self.docs = [_tokenize(_chunk_embedding_text(chunk)) for chunk in chunks]
        self.df: Counter[str] = Counter()
        for doc in self.docs:
            self.df.update(set(doc))
        self.avgdl = sum(len(doc) for doc in self.docs) / max(len(self.docs), 1)

    def query(self, query: str, top_k: int) -> list[dict[str, Any]]:
        terms = _tokenize(query)
        scores: list[tuple[float, int]] = []
        for index, doc in enumerate(self.docs):
            score = self._score(terms, doc)
            if score > 0:
                scores.append((score, index))
        scores.sort(reverse=True)
        matches: list[dict[str, Any]] = []
        for rank, (score, index) in enumerate(scores[:top_k], start=1):
            chunk = self.chunks[index]
            matches.append(
                {
                    "chunk_id": _chunk_id(chunk),
                    "rank": rank,
                    "bm25_rank": rank,
                    "document": _chunk_text(chunk),
                    "metadata": _chunk_metadata(chunk, index),
                    "score": score,
                    "bm25_score": score,
                    "retrieval_sources": ["bm25"],
                    "source_ranks": {"bm25": rank},
                }
            )
        return matches

    def _score(self, terms: list[str], doc: list[str]) -> float:
        counts = Counter(doc)
        dl = len(doc)
        score = 0.0
        k1 = 1.5
        b = 0.75
        total_docs = len(self.docs)
        for term in terms:
            tf = counts.get(term, 0)
            if tf <= 0:
                continue
            df = self.df.get(term, 0)
            idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
            score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / max(self.avgdl, 1)))
        return score


def adjudicate_top_rules(
    session_id: str,
    chunks: list[Any],
    rules: list[dict[str, Any]],
    retrievals: list[dict[str, Any]],
    max_issues: int,
) -> list[dict[str, Any]]:
    ranked = sorted(retrievals, key=lambda item: item.get("candidate_score", 0), reverse=True)
    issues: list[dict[str, Any]] = []
    for retrieval in ranked:
        if len(issues) >= max_issues:
            break
        rule = rules[retrieval["rule_index"]]
        evidence = retrieval.get("matches", [])[:8]
        missing_slot_ids = _missing_required_slot_ids(retrieval)
        if missing_slot_ids:
            issues.append(_missing_required_slot_issue(session_id, rule, evidence, retrieval, missing_slot_ids))
            continue
        if not evidence:
            continue
        issues.append(_adjudicate_rule(session_id, rule, evidence, retrieval))
    return issues


def _adjudicate_rule(
    session_id: str,
    rule: dict[str, Any],
    evidence: list[dict[str, Any]],
    retrieval: dict[str, Any],
) -> dict[str, Any]:
    structured_facts = retrieval.get("structured_facts", []) or []
    cross_chapter_findings = retrieval.get("cross_chapter_findings", []) or []
    execution_result = execute_rule_precheck(rule, evidence, structured_facts, cross_chapter_findings)
    payload = _call_deepseek_adjudicator(
        rule,
        evidence,
        structured_facts,
        cross_chapter_findings,
        execution_result,
        retrieval.get("slot_retrievals", []),
        retrieval.get("missing_required_slot_ids", []),
    )
    first = evidence[0]
    meta = first.get("metadata", {})
    bbox_list = []
    evidence_nodes = []
    for match in evidence:
        bbox_list.extend(_match_evidence_bboxes(match))
        evidence_nodes.extend(_match_evidence_block_ids(match))
    for fact in structured_facts:
        bbox_list.extend(fact.get("bbox_list") or [])
        evidence_nodes.extend(fact.get("block_ids") or [])
    for finding in cross_chapter_findings:
        bbox_list.extend(finding.get("bbox_list") or [])

    risk_level = payload.get("risk_level") or _severity_from_policy(rule.get("severity_policy", ""))
    confidence = int(payload.get("confidence") or min(95, max(55, int(first.get("score", 0.5) * 100))))
    reasoning = {
        "issue_type": rule.get("category", "规则库审查"),
        "rule_id": rule.get("rule_id", ""),
        "rule_name": rule.get("rule_name", ""),
        "rule_source": rule.get("rule_source", ""),
        "rule_description": _rule_description(rule),
        "review_topic": rule.get("review_topic", {}),
        "review_item": rule.get("review_item", {}),
        "review_logic": rule.get("review_logic", []),
        "evidence_scope": rule.get("evidence_scope", {}),
        "rule_execution": {
            "plan": rule.get("rule_execution", {}),
            "result": execution_result,
        },
        "severity_policy": rule.get("severity_policy", ""),
        "evidence_requirement": rule.get("evidence_requirement", ""),
        "actual_value": payload.get("actual_value", "见召回证据"),
        "expected_value": payload.get("expected_value", rule.get("evidence_requirement", "")),
        "evidence_nodes": evidence_nodes,
        "source_bbox_list": bbox_list,
        "fact_ids": retrieval.get("fact_ids", []),
        "structured_facts": structured_facts,
        "cross_chapter_findings": cross_chapter_findings,
        "evidence_slot_retrievals": retrieval.get("slot_retrievals", []),
        "missing_required_slot_ids": retrieval.get("missing_required_slot_ids", []),
        "langextract_grounding": {
            "fact_count": len(structured_facts),
            "finding_count": len(cross_chapter_findings),
            "source": "langextract",
        },
        "retrieval_scores": [
            {
                "chunk_id": match.get("chunk_id"),
                "score": match.get("score"),
                "vector_score": match.get("vector_score"),
                "bm25_score": match.get("bm25_score"),
                "rerank_score": match.get("rerank_score"),
                "rerank_rank": match.get("rerank_rank"),
                "evidence_slot_ids": match.get("evidence_slot_ids", []),
                "slot_queries": match.get("slot_queries", []),
            }
            for match in evidence
        ],
        "review_status": "pending",
        "conclusion_type": payload.get("conclusion_type", "issue"),
    }
    evidence_text = "\n\n".join(_match_evidence_text(match)[:800] for match in evidence[:3])
    return {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "clause_text": evidence_text,
        "page_number": int(meta.get("page_start") or 1),
        "paragraph_index": int(meta.get("chunk_index") or 0),
        "highlight_anchor": first.get("chunk_id", ""),
        "char_offset_start": 0,
        "char_offset_end": len(evidence_text),
        "risk_level": risk_level,
        "confidence_score": confidence,
        "source_type": "hybrid",
        "risk_category": rule.get("category", "规则库审查"),
        "ai_finding": payload.get("issue_desc") or f"{rule.get('rule_name', '规则审查')}：召回证据显示该规则需要人工复核。",
        "ai_reasoning": json.dumps(reasoning, ensure_ascii=False),
        "suggested_revision": payload.get("fix_suggestion") or _generic_suggestion(rule),
        "human_decision": "pending",
    }


def _missing_required_slot_issue(
    session_id: str,
    rule: dict[str, Any],
    evidence: list[dict[str, Any]],
    retrieval: dict[str, Any],
    missing_slot_ids: list[str],
) -> dict[str, Any]:
    first = evidence[0] if evidence else {}
    meta = first.get("metadata", {}) if isinstance(first.get("metadata"), dict) else {}
    bbox_list = []
    evidence_nodes = []
    for match in evidence:
        bbox_list.extend(_match_evidence_bboxes(match))
        evidence_nodes.extend(_match_evidence_block_ids(match))
    evidence_text = "\n\n".join(_match_evidence_text(match)[:800] for match in evidence[:3])
    actual_value = f"缺失必填证据槽位：{'、'.join(missing_slot_ids)}"
    expected_value = "每个 required evidence_slot 至少命中 min_matches 且覆盖 expected_terms 后，才能执行规则结论判断。"
    reasoning = {
        "issue_type": rule.get("category", "规则库审查"),
        "rule_id": rule.get("rule_id", ""),
        "rule_name": rule.get("rule_name", ""),
        "rule_source": rule.get("rule_source", ""),
        "rule_description": _rule_description(rule),
        "review_topic": rule.get("review_topic", {}),
        "review_item": rule.get("review_item", {}),
        "review_logic": rule.get("review_logic", []),
        "evidence_scope": rule.get("evidence_scope", {}),
        "rule_execution": {
            "plan": rule.get("rule_execution", {}),
            "result": {
                "execution_status": "needs_evidence",
                "checks": [
                    {
                        "type": "evidence_slot_required_presence",
                        "status": "needs_evidence",
                        "reason": "正式 RAG 审查缺失必填证据槽位，已跳过 LLM 结论判断。",
                        "missing_required_slot_ids": missing_slot_ids,
                    }
                ],
                "llm_required": False,
            },
        },
        "evidence_requirement": rule.get("evidence_requirement", ""),
        "actual_value": actual_value,
        "expected_value": expected_value,
        "evidence_nodes": evidence_nodes,
        "source_bbox_list": bbox_list,
        "fact_ids": retrieval.get("fact_ids", []),
        "structured_facts": retrieval.get("structured_facts", []) or [],
        "cross_chapter_findings": retrieval.get("cross_chapter_findings", []) or [],
        "evidence_slot_retrievals": retrieval.get("slot_retrievals", []),
        "missing_required_slot_ids": missing_slot_ids,
        "langextract_grounding": {
            "fact_count": len(retrieval.get("structured_facts", []) or []),
            "finding_count": len(retrieval.get("cross_chapter_findings", []) or []),
            "source": "langextract",
        },
        "retrieval_scores": [
            {
                "chunk_id": match.get("chunk_id"),
                "score": match.get("score"),
                "vector_score": match.get("vector_score"),
                "bm25_score": match.get("bm25_score"),
                "rerank_score": match.get("rerank_score"),
                "rerank_rank": match.get("rerank_rank"),
                "evidence_slot_ids": match.get("evidence_slot_ids", []),
                "slot_queries": match.get("slot_queries", []),
            }
            for match in evidence
        ],
        "review_status": "needs_evidence",
        "conclusion_type": "needs_evidence",
    }
    return {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "clause_text": evidence_text or actual_value,
        "page_number": int(meta.get("page_start") or 1),
        "paragraph_index": int(meta.get("chunk_index") or 0),
        "highlight_anchor": first.get("chunk_id", ""),
        "char_offset_start": 0,
        "char_offset_end": len(evidence_text or actual_value),
        "risk_level": "HIGH",
        "confidence_score": 0,
        "source_type": "hybrid",
        "risk_category": rule.get("category", "规则库审查"),
        "ai_finding": f"{rule.get('rule_name', '规则审查')}：{actual_value}，未执行 AI 结论判断。",
        "ai_reasoning": json.dumps(reasoning, ensure_ascii=False),
        "suggested_revision": "调整 evidence_slots.queries、补充解析/索引内容，或补齐原文证据后重新审查。",
        "human_decision": "pending",
    }


def _missing_required_slot_ids(retrieval: dict[str, Any]) -> list[str]:
    return [
        str(slot_id)
        for slot_id in retrieval.get("missing_required_slot_ids", [])
        if str(slot_id).strip()
    ]


def _call_deepseek_adjudicator(
    rule: dict[str, Any],
    evidence: list[dict[str, Any]],
    structured_facts: list[dict[str, Any]],
    cross_chapter_findings: list[dict[str, Any]],
    execution_result: dict[str, Any],
    evidence_slot_retrievals: list[dict[str, Any]] | None = None,
    missing_required_slot_ids: list[str] | None = None,
) -> dict[str, Any]:
    from langchain_core.messages import HumanMessage, SystemMessage

    prompt = {
        "rule": {
            "rule_id": rule.get("rule_id"),
            "rule_name": rule.get("rule_name"),
            "category": rule.get("category"),
            "review_topic": rule.get("review_topic", {}),
            "review_item": rule.get("review_item", {}),
            "review_logic": rule.get("review_logic", []),
            "evidence_scope": rule.get("evidence_scope", {}),
            "rule_execution_plan": rule.get("rule_execution", {}),
            "target_fields": rule.get("target_fields", []),
            "severity_policy": rule.get("severity_policy"),
            "evidence_requirement": rule.get("evidence_requirement"),
            "evidence_slots": [
                {
                    "slot_id": _slot_id(slot),
                    "label": slot.get("label"),
                    "required": slot.get("required") is True,
                    "expected_terms": _string_list(slot.get("expected_terms")),
                    "queries": _slot_queries(slot),
                }
                for slot in rule.get("evidence_slots", [])
                if isinstance(slot, dict)
            ],
        },
        "rule_execution_result": execution_result,
        "evidence_slot_retrievals": evidence_slot_retrievals or [],
        "missing_required_slot_ids": missing_required_slot_ids or [],
        "evidence": [
            {
                "chunk_id": match.get("chunk_id"),
                "evidence_slot_ids": match.get("evidence_slot_ids", []),
                "slot_queries": match.get("slot_queries", []),
                "page_start": match.get("metadata", {}).get("page_start"),
                "page_end": match.get("metadata", {}).get("page_end"),
                "section": match.get("metadata", {}).get("section"),
                "text": _match_evidence_text(match)[:1200],
            }
            for match in evidence[:8]
        ],
        "structured_facts": structured_facts[:12],
        "cross_chapter_findings": cross_chapter_findings[:6],
        "output_schema": {
            "risk_level": "HIGH|MEDIUM|LOW",
            "issue_desc": "问题描述，必须基于证据，不能新增事实",
            "actual_value": "从证据中可见的实际情况或材料中未见明确表述",
            "expected_value": "规则要求",
            "fix_suggestion": "具体修改建议",
            "confidence": "0-100整数",
            "conclusion_type": "issue|needs_review|attention",
        },
    }
    messages = [
        SystemMessage(
            content=(
                "你是水土保持方案技术审查助手。只基于提供的规则和证据输出 JSON，"
                "必须先遵循 review_topic -> review_item -> review_rule -> evidence_scope -> rule_execution 的审查路径，"
                "rule_execution_result 是确定性预检查结果，可用于识别缺失字段、证据范围覆盖和跨章节一致性线索。"
                "structured_facts 是 LangExtract 从原文定位出的结构化事实，"
                "cross_chapter_findings 是基于这些事实形成的跨章节核验线索。"
                "不要输出 markdown，不要新增证据中没有的事实。"
            )
        ),
        HumanMessage(content=json.dumps(prompt, ensure_ascii=False)),
    ]
    try:
        response = get_llm().invoke(messages)
        content = str(response.content).strip()
        if content.startswith("```"):
            content = "\n".join(content.splitlines()[1:-1]).strip()
        data = json.loads(content)
    except Exception as exc:
        raise RAGReviewError(f"DeepSeek rule adjudication failed: {exc}") from exc
    if not isinstance(data, dict):
        raise RAGReviewError("DeepSeek adjudication response is not a JSON object")
    return data


def _rrf(vector_matches: list[dict[str, Any]], bm25_matches: list[dict[str, Any]], k: int = 60) -> list[dict[str, Any]]:
    combined: dict[str, dict[str, Any]] = {}
    for source, matches in [("vector", vector_matches), ("bm25", bm25_matches)]:
        for rank, match in enumerate(matches, start=1):
            chunk_id = match["chunk_id"]
            entry = combined.setdefault(chunk_id, {**match, "score": 0.0})
            entry["score"] = float(entry.get("score", 0.0)) + 1.0 / (k + rank)
            _merge_retrieval_sources(entry, match)
            if source == "vector":
                source_rank = int(match.get("vector_rank") or rank)
                entry["vector_rank"] = source_rank
                entry["vector_score"] = match.get("vector_score", match.get("score"))
            else:
                source_rank = int(match.get("bm25_rank") or rank)
                entry["bm25_rank"] = source_rank
                entry["bm25_score"] = match.get("bm25_score", match.get("score"))
            _add_retrieval_source(entry, source, source_rank)
    return sorted(combined.values(), key=lambda item: item.get("score", 0), reverse=True)


def _expand_neighbors(
    matches: list[dict[str, Any]],
    chunks: list[Any],
    by_id: dict[str, Any],
    by_index: dict[str, int],
    limit: int = 8,
) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    seen: set[str] = set()
    for match in matches:
        for candidate_id in [match["chunk_id"], *_neighbor_ids(match["chunk_id"], chunks, by_index)]:
            if candidate_id in seen or candidate_id not in by_id:
                continue
            seen.add(candidate_id)
            if candidate_id == match["chunk_id"]:
                expanded.append(match)
            else:
                chunk = by_id[candidate_id]
                neighbor = {
                    "chunk_id": candidate_id,
                    "document": _chunk_text(chunk),
                    "metadata": _chunk_metadata(chunk, by_index[candidate_id]),
                    "score": match.get("score", 0) * 0.85,
                    "neighbor_of": match["chunk_id"],
                    "neighbor_rank": len(expanded) + 1,
                }
                _add_retrieval_source(neighbor, "neighbor", neighbor["neighbor_rank"])
                expanded.append(neighbor)
    return expanded[:limit]


def _with_final_ranks(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for rank, match in enumerate(matches, start=1):
        item = dict(match)
        if item.get("rerank_rank") is not None:
            _add_retrieval_source(item, "rerank", int(item["rerank_rank"]))
        item["final_rank"] = rank
        item["retrieval_sources"] = sorted(set(_retrieval_sources(item)))
        item["source_ranks"] = _retrieval_source_ranks(item)
        ranked.append(item)
    return ranked


def _retrieval_mode(
    vector_available: bool,
    bm25_available: bool,
    neighbors_enabled: bool,
    rerank_available: bool,
) -> str:
    parts: list[str] = []
    if vector_available:
        parts.append("vector")
    if bm25_available:
        parts.append("bm25")
    if neighbors_enabled:
        parts.append("neighbor")
    if rerank_available:
        parts.append("rerank")
    return "_".join(parts) if parts else "unavailable"


def _merge_retrieval_sources(target: dict[str, Any], source: dict[str, Any]) -> None:
    target["retrieval_sources"] = sorted(set(_retrieval_sources(target)) | set(_retrieval_sources(source)))
    ranks = _retrieval_source_ranks(target)
    ranks.update(_retrieval_source_ranks(source))
    target["source_ranks"] = ranks


def _add_retrieval_source(match: dict[str, Any], source: str, rank: int) -> None:
    match["retrieval_sources"] = sorted(set(_retrieval_sources(match)) | {source})
    ranks = _retrieval_source_ranks(match)
    ranks[source] = rank
    match["source_ranks"] = ranks


def _retrieval_sources(match: dict[str, Any]) -> list[str]:
    sources = match.get("retrieval_sources")
    if not isinstance(sources, list):
        return []
    return [str(source) for source in sources if source]


def _retrieval_source_ranks(match: dict[str, Any]) -> dict[str, int]:
    ranks = match.get("source_ranks")
    if not isinstance(ranks, dict):
        return {}
    normalized: dict[str, int] = {}
    for source, rank in ranks.items():
        if isinstance(rank, bool) or not isinstance(rank, (int, float)):
            continue
        normalized[str(source)] = int(rank)
    return normalized


def _neighbor_ids(chunk_id: str, chunks: list[Any], by_index: dict[str, int]) -> list[str]:
    index = by_index.get(chunk_id)
    if index is None:
        return []
    seed = chunks[index]
    seed_pages = set(_page_range(seed))
    seed_tables = set(getattr(seed, "table_refs", []) or [])
    ids: list[str] = []
    for neighbor_index in [index - 1, index + 1]:
        if 0 <= neighbor_index < len(chunks):
            ids.append(_chunk_id(chunks[neighbor_index]))
    same_page = [
        (abs(other_index - index), _chunk_id(chunk))
        for other_index, chunk in enumerate(chunks)
        if other_index != index and seed_pages.intersection(_page_range(chunk))
    ]
    same_page.sort(key=lambda item: item[0])
    ids.extend(chunk_id for _, chunk_id in same_page[:3])
    if seed_tables:
        table_related = [
            (abs(other_index - index), _chunk_id(chunk))
            for other_index, chunk in enumerate(chunks)
            if other_index != index and seed_tables.intersection(set(getattr(chunk, "table_refs", []) or []))
        ]
        table_related.sort(key=lambda item: item[0])
        ids.extend(chunk_id for _, chunk_id in table_related[:3])
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate_id in ids:
        if candidate_id and candidate_id not in seen:
            seen.add(candidate_id)
            deduped.append(candidate_id)
    return deduped


def _page_range(chunk: Any) -> list[int]:
    page_range = getattr(chunk, "page_range", [1, 1])
    if not page_range:
        return [1]
    start = int(page_range[0])
    end = int(page_range[-1])
    return list(range(start, end + 1))


def _candidate_score(
    rule: dict[str, Any],
    matches: list[dict[str, Any]],
    facts: list[dict[str, Any]] | None = None,
    findings: list[dict[str, Any]] | None = None,
) -> float:
    severity = _severity_from_policy(rule.get("severity_policy", ""))
    severity_weight = {"HIGH": 3.0, "MEDIUM": 2.0, "LOW": 1.0}.get(severity, 1.0)
    retrieval_score = sum(float(match.get("score", 0)) for match in matches[:3])
    fact_bonus = min(1.5, len(facts or []) * 0.12)
    finding_bonus = min(2.0, len(findings or []) * 0.5)
    return severity_weight + retrieval_score + fact_bonus + finding_bonus


def _facts_for_rule(rule: dict[str, Any], facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not facts:
        return []
    query = _rule_query(rule)
    target_text = " ".join(str(item) for item in rule.get("target_fields", []))
    haystack = f"{query}\n{target_text}"
    ranked: list[tuple[int, dict[str, Any]]] = []
    for fact in facts:
        field_name = str(fact.get("field_name", ""))
        label = _field_label(field_name)
        score = 0
        if field_name and field_name in target_text:
            score += 5
        if label and label in haystack:
            score += 4
        if any(keyword in haystack for keyword in _fact_keywords(field_name)):
            score += 3
        if str(fact.get("section", "")) and str(fact.get("section", "")) in haystack:
            score += 1
        if score:
            ranked.append((score, fact))
    ranked.sort(key=lambda item: (item[0], int(item[1].get("confidence") or 0)), reverse=True)
    return [fact for _, fact in ranked]


def _findings_for_rule(
    rule: dict[str, Any],
    findings: list[dict[str, Any]],
    facts: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not findings:
        return []
    query = _rule_query(rule)
    fact_ids = {fact.get("fact_id") for fact in facts}
    ranked: list[tuple[int, dict[str, Any]]] = []
    for finding in findings:
        field_name = str(finding.get("field_name", ""))
        label = _field_label(field_name)
        score = 0
        if any(fact_id in fact_ids for fact_id in finding.get("fact_ids", [])):
            score += 5
        if (label and label in query) or (field_name and field_name in query):
            score += 4
        if any(keyword in query for keyword in _fact_keywords(field_name)):
            score += 3
        if score:
            ranked.append((score, finding))
    ranked.sort(key=lambda item: (item[0], int(item[1].get("confidence") or 0)), reverse=True)
    return [finding for _, finding in ranked]


def _compact_fact(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "fact_id": fact.get("fact_id"),
        "field_name": fact.get("field_name"),
        "field_label": _field_label(str(fact.get("field_name", ""))),
        "value": fact.get("value"),
        "normalized_value": fact.get("normalized_value"),
        "unit": fact.get("unit"),
        "section": fact.get("section"),
        "chunk_id": fact.get("chunk_id"),
        "page_range": fact.get("page_range"),
        "source_text": str(fact.get("source_text", ""))[:400],
        "block_ids": fact.get("block_ids", [])[:20],
        "bbox_count": len(fact.get("bbox_list") or []),
        "bbox_list": fact.get("bbox_list", [])[:20],
        "confidence": fact.get("confidence"),
    }


def _compact_finding(finding: dict[str, Any]) -> dict[str, Any]:
    return {
        "finding_id": finding.get("finding_id"),
        "finding_type": finding.get("finding_type"),
        "field_name": finding.get("field_name"),
        "description": finding.get("description"),
        "risk_level": finding.get("risk_level"),
        "actual_value": finding.get("actual_value"),
        "expected_value": finding.get("expected_value"),
        "fact_ids": finding.get("fact_ids", []),
        "source_pages": finding.get("source_pages", []),
        "bbox_count": len(finding.get("bbox_list") or []),
        "bbox_list": finding.get("bbox_list", [])[:20],
        "evidence_text": str(finding.get("evidence_text", ""))[:600],
        "confidence": finding.get("confidence"),
    }


def _field_label(field_name: str) -> str:
    labels = {
        "project_name": "项目名称",
        "construction_unit": "建设单位",
        "construction_location": "建设地点",
        "project_nature": "建设性质",
        "key_prevention_or_control_area": "重点防治区",
        "disturbed_area": "扰动地表面积",
        "land_area": "占地面积",
        "prevention_responsibility_area": "防治责任范围",
        "zone_area": "分区面积",
        "excavation_volume": "挖方",
        "fill_volume": "填方",
        "borrow_volume": "借方",
        "spoil_volume": "弃方",
        "comprehensive_utilization": "综合利用",
        "spoil_destination": "外运去向",
        "topsoil_stripping": "表土剥离",
        "topsoil_preservation": "表土保存",
        "topsoil_backfill": "表土回覆",
        "temp_soil_stockpile": "临时堆土区",
        "borrow_area": "取土场",
        "spoil_area": "弃渣场",
        "construction_road": "施工道路",
        "prevention_measures": "防治措施",
        "monitoring": "监测",
        "schedule_arrangement": "时序安排",
        "investment_estimate": "投资估算",
        "earthwork_balance": "土石方平衡",
        "topsoil_protection": "表土保护",
        "area": "面积",
    }
    return labels.get(field_name, field_name)


def _fact_keywords(field_name: str) -> list[str]:
    keywords = {
        "earthwork_balance": ["土石方", "挖方", "填方", "借方", "弃方"],
        "spoil_destination": ["弃方", "弃渣", "弃土", "外运", "消纳", "综合利用"],
        "topsoil_protection": ["表土", "剥离", "保存", "回覆", "堆存"],
        "area": ["面积", "扰动", "占地", "防治责任范围"],
    }
    if field_name in keywords:
        return keywords[field_name]
    label = _field_label(field_name)
    return [label] if label else []


def _rule_query(rule: dict[str, Any]) -> str:
    scope = rule.get("evidence_scope", {}) or {}
    logic_labels = " ".join(str(item.get("label", "")) for item in rule.get("review_logic", []))
    parts = [
        rule.get("expert_brief_query", ""),
        rule.get("review_topic", {}).get("name", ""),
        rule.get("review_item", {}).get("name", ""),
        rule.get("rule_name", ""),
        rule.get("category", ""),
        logic_labels,
        " ".join(str(item) for item in rule.get("target_fields", [])),
        " ".join(str(item) for item in scope.get("chapters", [])),
        " ".join(str(item) for item in scope.get("tables", [])),
        " ".join(str(item) for item in scope.get("attachments", [])),
        " ".join(str(item) for item in scope.get("regulations", [])),
        rule.get("evidence_requirement", ""),
        rule.get("severity_policy", ""),
        rule.get("review_criteria", ""),
        rule.get("expected_result", ""),
        " ".join(str(item) for item in rule.get("failure_conditions", [])),
        " ".join(str(item) for item in rule.get("regulation_clauses", [])),
        rule.get("rule_source", ""),
    ]
    return "\n".join(part for part in parts if part)


def _rule_description(rule: dict[str, Any]) -> str:
    targets = "、".join(str(item) for item in rule.get("target_fields", []) if str(item).strip())
    pieces = []
    if rule.get("rule_source"):
        pieces.append(str(rule["rule_source"]))
    if targets:
        pieces.append(f"重点核查字段：{targets}")
    if rule.get("severity_policy"):
        pieces.append(f"判定策略：{rule['severity_policy']}")
    return "；".join(pieces)


def _match_evidence_text(match: dict[str, Any]) -> str:
    metadata = match.get("metadata") if isinstance(match.get("metadata"), dict) else {}
    return str(metadata.get("evidence_window_text") or match.get("document") or "")


def _chunk_text(chunk: Any) -> str:
    return getattr(chunk, "text", "")


def _chunk_embedding_text(chunk: Any) -> str:
    enriched = str(getattr(chunk, "embedding_text", "") or "").strip()
    return enriched or _chunk_text(chunk)


def _chunk_id(chunk: Any) -> str:
    return getattr(chunk, "chunk_id", "")


def _chunk_metadata(chunk: Any, index: int, index_content_hash: str | None = None) -> dict[str, Any]:
    bbox_list = getattr(chunk, "bbox_list", [])
    block_ids = [item.get("block_id") for item in bbox_list if item.get("block_id")]
    page_range = getattr(chunk, "page_range", [1, 1])
    chunk_meta = getattr(chunk, "metadata", {})
    if not isinstance(chunk_meta, dict):
        chunk_meta = {}
    metadata = {
        "chunk_id": _chunk_id(chunk),
        "chunk_index": index,
        "index_content_hash": index_content_hash or "",
        "section": getattr(chunk, "section", ""),
        "page_start": int(page_range[0] if page_range else 1),
        "page_end": int(page_range[-1] if page_range else 1),
        "bbox_json": json.dumps(bbox_list, ensure_ascii=False),
        "block_ids_json": json.dumps(chunk_meta.get("block_ids") or block_ids, ensure_ascii=False),
        "table_refs_json": json.dumps(getattr(chunk, "table_refs", []), ensure_ascii=False),
        "chunk_layer": str(chunk_meta.get("chunk_layer") or ""),
        "parent_section": str(chunk_meta.get("parent_section") or ""),
        "block_types_json": json.dumps(chunk_meta.get("block_types", []), ensure_ascii=False),
        "block_sub_types_json": json.dumps(chunk_meta.get("block_sub_types", []), ensure_ascii=False),
        "mineru_indexes_json": json.dumps(chunk_meta.get("mineru_indexes", []), ensure_ascii=False),
        "child_types_json": json.dumps(chunk_meta.get("child_types", []), ensure_ascii=False),
        "span_types_json": json.dumps(chunk_meta.get("span_types", []), ensure_ascii=False),
        "page_sizes_json": json.dumps(chunk_meta.get("page_sizes", {}), ensure_ascii=False),
        "captions_json": json.dumps(chunk_meta.get("captions", []), ensure_ascii=False),
        "atomic_block_ids_json": json.dumps(chunk_meta.get("atomic_block_ids", []), ensure_ascii=False),
        "evidence_window_block_ids_json": json.dumps(chunk_meta.get("evidence_window_block_ids", []), ensure_ascii=False),
        "evidence_window_bbox_json": json.dumps(chunk_meta.get("evidence_window_bbox_list", []), ensure_ascii=False),
        "evidence_window_text": str(chunk_meta.get("evidence_window_text") or "")[:2400],
        "has_table": bool(chunk_meta.get("has_table")),
        "has_image": bool(chunk_meta.get("has_image")),
    }
    embedding_text = _chunk_embedding_text(chunk)
    if embedding_text != _chunk_text(chunk):
        metadata["embedding_enriched"] = True
        metadata["embedding_text_sha1"] = hashlib.sha1(embedding_text.encode("utf-8")).hexdigest()
    else:
        metadata["embedding_enriched"] = False
    return metadata


def _index_content_hash(chunks: list[Any]) -> str:
    payload = [
        {
            "chunk_id": _chunk_id(chunk),
            "document": _chunk_text(chunk),
            "embedding_text": _chunk_embedding_text(chunk),
            "section": getattr(chunk, "section", ""),
            "page_range": getattr(chunk, "page_range", []),
            "metadata": getattr(chunk, "metadata", {}),
        }
        for chunk in chunks
    ]
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _existing_index_hash_matches(metadatas: Any, index_content_hash: str) -> bool:
    if not isinstance(metadatas, list) or not metadatas:
        return False
    hashes = {metadata.get("index_content_hash") for metadata in metadatas if isinstance(metadata, dict)}
    return hashes == {index_content_hash}


def _match_evidence_bboxes(match: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = match.get("metadata") if isinstance(match.get("metadata"), dict) else {}
    window_bboxes = _loads_json_list(metadata.get("evidence_window_bbox_json"))
    return [item for item in (window_bboxes or _loads_json_list(metadata.get("bbox_json"))) if isinstance(item, dict)]


def _match_evidence_block_ids(match: dict[str, Any]) -> list[str]:
    metadata = match.get("metadata") if isinstance(match.get("metadata"), dict) else {}
    window_ids = _loads_json_list(metadata.get("evidence_window_block_ids_json"))
    block_ids = window_ids or _loads_json_list(metadata.get("block_ids_json"))
    return [str(item) for item in block_ids if str(item).strip()]


def _loads_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _tokenize(text: str) -> list[str]:
    words = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9_.-]+", text.lower())
    tokens: list[str] = []
    for word in words:
        if re.match(r"^[\u4e00-\u9fff]+$", word) and len(word) > 3:
            tokens.extend(word[i : i + 2] for i in range(len(word) - 1))
        tokens.append(word)
    return tokens


def _severity_from_policy(policy: str) -> str:
    if "重大" in policy or "严重" in policy:
        return "HIGH"
    if "一般" in policy:
        return "MEDIUM"
    return "LOW"


def _generic_suggestion(rule: dict[str, Any]) -> str:
    requirement = rule.get("evidence_requirement") or "规则要求"
    return f"请补充或核验与“{rule.get('rule_name', '规则')}”相关的证明材料。要求：{requirement}"


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
