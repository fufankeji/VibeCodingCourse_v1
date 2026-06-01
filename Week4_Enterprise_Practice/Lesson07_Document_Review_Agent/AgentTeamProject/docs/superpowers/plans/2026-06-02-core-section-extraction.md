# Core Section Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restrict water-review key-field extraction to project overview and earthwork-balance evidence selected through retrieval, while keeping existing artifacts and frontend contracts stable.

**Architecture:** Add a focused core-extraction service that selects project-overview and earthwork chunks before field extraction. Use the existing Chroma/BM25 retrieval path when available, fall back to BM25 and deterministic section/keyword filtering, and pass only selected chunks to fallback extraction and LangExtract. Keep full `chunks` for RAG review, evidence highlighting, and current artifact compatibility.

**Tech Stack:** Python 3.11, FastAPI service layer, Chroma-backed RAG service, deterministic regex extraction, LangExtract, pytest.

---

## File Structure

- Create: `backend/app/services/core_extraction_service.py`
  - Owns core query definitions, core field names, vector/BM25 selection, deterministic fallback filtering, trace payload generation, and artifact writing.
- Modify: `backend/app/services/water_review_extraction.py`
  - Restricts active fallback extraction to core fields while preserving `WATER_FIELDS` output order.
- Modify: `backend/app/services/langextract_service.py`
  - Restricts LangExtract prompt and accepted extraction classes to core fields while preserving full `WATER_FIELDS` output compatibility.
- Modify: `backend/app/services/water_review_service.py`
  - Calls core chunk selection after chunking and passes `core_chunks` to field extraction and LangExtract.
- Create: `backend/tests/test_core_extraction_service.py`
  - Covers retrieval fallback, deterministic filtering, trace artifact shape, and no-match full-chunk fallback.
- Modify: `backend/tests/test_langextract_service.py`
  - Covers that non-core facts are ignored and field output remains structurally compatible.
- Add or modify: `backend/tests/test_water_review_extraction.py`
  - Covers fallback extraction does not actively populate non-core fields from non-core sections.

---

### Task 1: Add Core Extraction Selection Service

**Files:**
- Create: `backend/app/services/core_extraction_service.py`
- Create: `backend/tests/test_core_extraction_service.py`

- [ ] **Step 1: Write failing tests for deterministic fallback selection**

Create `backend/tests/test_core_extraction_service.py`:

```python
from pathlib import Path

from app.services.core_extraction_service import build_core_extraction_chunks
from app.services.water_review_models import ReviewChunk


def _chunk(chunk_id: str, text: str, section: str) -> ReviewChunk:
    index = int(chunk_id.rsplit("-", 1)[-1])
    return ReviewChunk(
        chunk_id=chunk_id,
        text=text,
        section=section,
        page_range=[index, index],
        bbox_list=[],
        table_refs=[],
        metadata={},
        char_start=index * 100,
        char_end=index * 100 + len(text),
    )


def test_build_core_extraction_chunks_falls_back_to_project_and_earthwork_keywords(tmp_path):
    chunks = [
        _chunk("chunk-0001", "项目名称：测试项目。建设单位：测试公司。建设地点位于北京市。", "项目概况"),
        _chunk("chunk-0002", "水土保持监测采用定点监测和巡查。", "监测"),
        _chunk("chunk-0003", "土石方平衡：挖方10.00万m3，填方8.00万m3，借方0.00万m3，弃方2.00万m3。", "土石方平衡"),
    ]

    result = build_core_extraction_chunks(chunks, "session-core", tmp_path, store_factory=lambda: None)

    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk-0001", "chunk-0003"]
    assert result.mode in {"bm25", "keyword"}
    assert result.trace["selected_count"] == 2
    assert result.trace["fallback_used"] is True
    assert (tmp_path / "core_extraction_chunks.json").exists()


def test_build_core_extraction_chunks_returns_all_chunks_when_no_core_match(tmp_path):
    chunks = [
        _chunk("chunk-0001", "附图目录。", "附图"),
        _chunk("chunk-0002", "附件清单。", "附件"),
    ]

    result = build_core_extraction_chunks(chunks, "session-empty", tmp_path, store_factory=lambda: None)

    assert [chunk.chunk_id for chunk in result.chunks] == ["chunk-0001", "chunk-0002"]
    assert result.mode == "all_chunks_fallback"
    assert result.trace["selected_count"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend
uv run pytest tests/test_core_extraction_service.py -q
```

Expected: FAIL because `app.services.core_extraction_service` does not exist.

- [ ] **Step 3: Implement the minimal core extraction service**

Create `backend/app/services/core_extraction_service.py`:

```python
"""Select project-overview and earthwork chunks for focused extraction."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.config import settings
from app.services import rag_service

logger = logging.getLogger(__name__)

CORE_FIELD_NAMES = {
    "project_name",
    "construction_unit",
    "construction_location",
    "project_nature",
    "land_area",
    "disturbed_area",
    "prevention_responsibility_area",
    "excavation_volume",
    "fill_volume",
    "borrow_volume",
    "spoil_volume",
    "spoil_destination",
    "borrow_area",
    "comprehensive_utilization",
}

CORE_EXTRACTION_QUERIES = (
    "项目概况 项目名称 建设单位 建设地点 建设性质 占地面积 防治责任范围 扰动面积",
    "土石方平衡 挖方 填方 借方 弃方 余方 外运 消纳 综合利用 取土场 弃渣场",
)

CORE_SECTION_TERMS = (
    "项目概况",
    "综合说明",
    "工程概况",
    "土石方",
    "土石方平衡",
)

CORE_KEYWORDS = (
    "项目名称",
    "建设单位",
    "建设地点",
    "建设性质",
    "占地面积",
    "扰动地表面积",
    "防治责任范围",
    "土石方",
    "挖方",
    "填方",
    "借方",
    "弃方",
    "余方",
    "外运",
    "消纳",
    "综合利用",
    "取土场",
    "弃渣场",
)


@dataclass(frozen=True)
class CoreExtractionSelection:
    chunks: list[Any]
    mode: str
    trace: dict[str, Any]


def build_core_extraction_chunks(
    chunks: list[Any],
    session_id: str,
    artifact_dir: str | Path,
    *,
    store_factory: Callable[[], Any | None] | None = None,
) -> CoreExtractionSelection:
    artifact_path = Path(artifact_dir)
    artifact_path.mkdir(parents=True, exist_ok=True)
    if not chunks:
        result = CoreExtractionSelection([], "empty", _trace([], [], "empty", True, []))
        _write_trace(artifact_path, result.trace)
        return result

    errors: list[str] = []
    selected_ids: list[str] = []
    mode = "vector"
    store = None

    try:
        store = store_factory() if store_factory is not None else _default_store(chunks, session_id)
    except Exception as exc:
        errors.append(f"vector_unavailable: {exc}")
        store = None

    try:
        for query in CORE_EXTRACTION_QUERIES:
            retrieval = rag_service.retrieve_for_query(
                chunks,
                query,
                top_k=min(max(settings.rag_top_k, 8), 16),
                store=store,
                use_bm25=True,
                use_neighbors=True,
                use_rerank=False,
            )
            selected_ids.extend(str(match.get("chunk_id") or "") for match in retrieval.get("matches", []))
        if store is None:
            mode = "bm25"
    except Exception as exc:
        errors.append(f"retrieval_failed: {exc}")
        selected_ids = []
        mode = "keyword"

    selected = _chunks_by_ids_in_source_order(chunks, selected_ids)
    if not selected:
        selected = _keyword_core_chunks(chunks)
        mode = "keyword"

    fallback_used = store is None or bool(errors) or mode in {"bm25", "keyword", "all_chunks_fallback"}
    if not selected:
        selected = list(chunks)
        mode = "all_chunks_fallback"
        fallback_used = True

    result = CoreExtractionSelection(
        selected,
        mode,
        _trace(chunks, selected, mode, fallback_used, errors),
    )
    _write_trace(artifact_path, result.trace)
    return result


def _default_store(chunks: list[Any], session_id: str) -> rag_service.ChromaChunkStore:
    vector_dir = Path(settings.storage_path) / "vector_stores" / "water_review" / session_id
    vector_dir.mkdir(parents=True, exist_ok=True)
    store = rag_service.ChromaChunkStore(vector_dir, session_id, rag_service.SiliconFlowEmbeddingProvider())
    store.rebuild(chunks)
    return store


def _chunks_by_ids_in_source_order(chunks: list[Any], chunk_ids: list[str]) -> list[Any]:
    wanted = {chunk_id for chunk_id in chunk_ids if chunk_id}
    return [chunk for chunk in chunks if str(getattr(chunk, "chunk_id", "")) in wanted]


def _keyword_core_chunks(chunks: list[Any]) -> list[Any]:
    selected = []
    for chunk in chunks:
        haystack = f"{getattr(chunk, 'section', '')}\n{getattr(chunk, 'text', '')}"
        if any(term in haystack for term in CORE_SECTION_TERMS) or any(term in haystack for term in CORE_KEYWORDS):
            selected.append(chunk)
    return selected


def _trace(
    all_chunks: list[Any],
    selected_chunks: list[Any],
    mode: str,
    fallback_used: bool,
    errors: list[str],
) -> dict[str, Any]:
    return {
        "mode": mode,
        "fallback_used": fallback_used,
        "input_count": len(all_chunks),
        "selected_count": len(selected_chunks),
        "queries": list(CORE_EXTRACTION_QUERIES),
        "errors": errors,
        "chunks": [
            {
                "chunk_id": str(getattr(chunk, "chunk_id", "")),
                "section": str(getattr(chunk, "section", "")),
                "page_range": list(getattr(chunk, "page_range", []) or []),
            }
            for chunk in selected_chunks
        ],
    }


def _write_trace(artifact_dir: Path, trace: dict[str, Any]) -> None:
    path = artifact_dir / "core_extraction_chunks.json"
    path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd backend
uv run pytest tests/test_core_extraction_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/core_extraction_service.py backend/tests/test_core_extraction_service.py
git commit -m "feat: select core extraction chunks"
```

---

### Task 2: Restrict Deterministic Field Extraction To Core Fields

**Files:**
- Modify: `backend/app/services/water_review_extraction.py`
- Create or modify: `backend/tests/test_water_review_extraction.py`

- [ ] **Step 1: Write failing tests for core-only fallback extraction**

Create `backend/tests/test_water_review_extraction.py` if it does not exist. Add:

```python
from app.services.water_review_extraction import extract_fields
from app.services.water_review_models import ReviewChunk, WATER_FIELDS


def _chunk(text: str, section: str = "项目概况") -> ReviewChunk:
    return ReviewChunk(
        chunk_id="chunk-0001",
        text=text,
        section=section,
        page_range=[1, 1],
        bbox_list=[],
        table_refs=[],
        metadata={},
        char_start=0,
        char_end=len(text),
    )


def _field(fields: list[dict], name: str) -> dict:
    return next(item for item in fields if item["field_name"] == name)


def test_extract_fields_keeps_output_shape_but_only_populates_core_fields():
    fields = extract_fields(
        [
            _chunk(
                "项目名称：测试水保项目。建设单位：测试建设公司。建设地点：北京市朝阳区。"
                "本项目总占地面积1.20hm2，防治责任范围面积1.20hm2。"
                "水土保持监测采用巡查监测，水土保持投资100万元。",
                "项目概况",
            )
        ]
    )

    assert [item["field_name"] for item in fields] == WATER_FIELDS
    assert _field(fields, "project_name")["value"] == "测试水保项目"
    assert _field(fields, "construction_unit")["value"] == "测试建设公司"
    assert _field(fields, "monitoring")["value"] == ""
    assert _field(fields, "investment_estimate")["value"] == ""


def test_extract_fields_populates_core_earthwork_fields():
    fields = extract_fields(
        [
            _chunk(
                "土石方平衡：挖方10.00万m3，填方8.00万m3，借方0.00万m3，弃方2.00万m3，余方外运综合利用。",
                "土石方平衡",
            )
        ]
    )

    assert _field(fields, "excavation_volume")["normalized_value"] == "10.00"
    assert _field(fields, "fill_volume")["normalized_value"] == "8.00"
    assert _field(fields, "borrow_volume")["normalized_value"] == "0.00"
    assert _field(fields, "spoil_volume")["normalized_value"] == "2.00"
    assert _field(fields, "comprehensive_utilization")["value"] == "综合利用"
```

- [ ] **Step 2: Run tests to verify at least one fails**

Run:

```bash
cd backend
uv run pytest tests/test_water_review_extraction.py -q
```

Expected: FAIL because existing extraction still populates non-core keyword fields such as `monitoring` and `investment_estimate`.

- [ ] **Step 3: Update extraction constants and active fields**

In `backend/app/services/water_review_extraction.py`, add:

```python
CORE_EXTRACTION_FIELDS = {
    "project_name",
    "construction_unit",
    "construction_location",
    "project_nature",
    "land_area",
    "disturbed_area",
    "prevention_responsibility_area",
    "excavation_volume",
    "fill_volume",
    "borrow_volume",
    "spoil_volume",
    "spoil_destination",
    "borrow_area",
    "comprehensive_utilization",
}
```

Replace the `keyword_fields` dictionary with:

```python
keyword_fields = {
    "comprehensive_utilization": ["综合利用"],
    "spoil_destination": ["外运", "消纳场", "弃土去向", "弃方去向"],
    "borrow_area": ["取土场"],
}
```

Keep the final return as:

```python
present = {item["field_name"]: item for item in extracted if item["field_name"] in CORE_EXTRACTION_FIELDS}
return [present.get(name) or _field(name, None, chunks) for name in WATER_FIELDS]
```

- [ ] **Step 4: Run extraction tests**

Run:

```bash
cd backend
uv run pytest tests/test_water_review_extraction.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/water_review_extraction.py backend/tests/test_water_review_extraction.py
git commit -m "fix: restrict fallback extraction to core fields"
```

---

### Task 3: Restrict LangExtract Accepted Fields And Candidate Inputs

**Files:**
- Modify: `backend/app/services/langextract_service.py`
- Modify: `backend/tests/test_langextract_service.py`

- [ ] **Step 1: Write failing LangExtract field-surface tests**

Append to `backend/tests/test_langextract_service.py`:

```python
from app.services.langextract_service import LANGEXTRACT_ALLOWED_FIELDS, build_fact_index, facts_to_extracted_fields


def test_langextract_allowed_fields_only_contains_core_extraction_fields():
    assert list(LANGEXTRACT_ALLOWED_FIELDS) == [
        "project_name",
        "construction_unit",
        "construction_location",
        "project_nature",
        "land_area",
        "disturbed_area",
        "prevention_responsibility_area",
        "excavation_volume",
        "fill_volume",
        "borrow_volume",
        "spoil_volume",
        "spoil_destination",
        "borrow_area",
        "comprehensive_utilization",
    ]


def test_facts_to_extracted_fields_ignores_non_core_langextract_fact():
    facts = [
        _fact("monitoring", "水土保持监测", "水土保持监测", "", "fact-monitoring"),
        _fact("project_name", "测试项目", "测试项目", "", "fact-project"),
    ]

    fields = facts_to_extracted_fields(facts)
    by_name = {item["field_name"]: item for item in fields}

    assert "monitoring" not in LANGEXTRACT_ALLOWED_FIELDS
    assert by_name["project_name"]["fact_id"] == "fact-project"
    assert by_name["monitoring"]["value"] == ""
    assert "monitoring" in build_fact_index(facts)["by_field"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend
uv run pytest tests/test_langextract_service.py::test_langextract_allowed_fields_only_contains_core_extraction_fields tests/test_langextract_service.py::test_facts_to_extracted_fields_ignores_non_core_langextract_fact -q
```

Expected: FAIL because `LANGEXTRACT_ALLOWED_FIELDS` does not exist yet.

- [ ] **Step 3: Restrict LangExtract accepted classes and prompt**

In `backend/app/services/langextract_service.py`, keep `FIELD_ORDER` unchanged so `facts_to_extracted_fields()` continues returning the full field structure. Add this constant below `FIELD_ORDER`:

```python
LANGEXTRACT_ALLOWED_FIELDS = (
    "project_name",
    "construction_unit",
    "construction_location",
    "project_nature",
    "land_area",
    "disturbed_area",
    "prevention_responsibility_area",
    "excavation_volume",
    "fill_volume",
    "borrow_volume",
    "spoil_volume",
    "spoil_destination",
    "borrow_area",
    "comprehensive_utilization",
)
```

Do not remove `FIELD_LABELS` entries used by existing conflict code. Add a separate prompt label map:

```python
LANGEXTRACT_PROMPT_FIELD_LABELS = {
    "project_name": "项目名称",
    "construction_unit": "建设单位",
    "construction_location": "建设地点",
    "project_nature": "建设性质",
    "land_area": "占地面积",
    "disturbed_area": "扰动地表面积",
    "prevention_responsibility_area": "防治责任范围面积",
    "excavation_volume": "挖方",
    "fill_volume": "填方",
    "borrow_volume": "借方",
    "spoil_volume": "弃方",
    "spoil_destination": "外运去向",
    "borrow_area": "取土场",
    "comprehensive_utilization": "综合利用",
}
```

Keep `FIELD_ALIASES` unchanged. In `_fact_from_extraction()`, replace:

```python
if field_name not in FIELD_ORDER:
    return None
```

with:

```python
if field_name not in LANGEXTRACT_ALLOWED_FIELDS:
    return None
```

Update `PROMPT_DESCRIPTION` so the allowed classes are exactly:

```text
project_name, construction_unit, construction_location, project_nature,
land_area, disturbed_area, prevention_responsibility_area,
excavation_volume, fill_volume, borrow_volume, spoil_volume,
spoil_destination, borrow_area, comprehensive_utilization。
```

Remove non-core examples for topsoil from `_examples()`.

- [ ] **Step 4: Run LangExtract tests**

Run:

```bash
cd backend
uv run pytest tests/test_langextract_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/langextract_service.py backend/tests/test_langextract_service.py
git commit -m "fix: limit langextract to core extraction fields"
```

---

### Task 4: Wire Core Chunks Into The Main Pipeline

**Files:**
- Modify: `backend/app/services/water_review_service.py`
- Modify: `backend/tests/test_core_extraction_service.py`

- [ ] **Step 1: Write a pipeline-level test for core chunk trace creation**

Add this test to `backend/tests/test_core_extraction_service.py`:

```python
def test_core_extraction_trace_records_mode_and_selected_chunks(tmp_path):
    chunks = [
        _chunk("chunk-0001", "项目名称：测试项目。建设单位：测试公司。", "项目概况"),
        _chunk("chunk-0002", "工程措施包括排水沟。", "防治措施"),
        _chunk("chunk-0003", "挖方10.00万m3，填方10.00万m3。", "土石方平衡"),
    ]

    result = build_core_extraction_chunks(chunks, "session-trace", tmp_path, store_factory=lambda: None)

    assert result.trace["mode"] in {"bm25", "keyword"}
    assert [item["chunk_id"] for item in result.trace["chunks"]] == ["chunk-0001", "chunk-0003"]
```

- [ ] **Step 2: Run the focused test**

Run:

```bash
cd backend
uv run pytest tests/test_core_extraction_service.py::test_core_extraction_trace_records_mode_and_selected_chunks -q
```

Expected: PASS after Task 1.

- [ ] **Step 3: Update `run_pipeline()` to use core chunks**

In `backend/app/services/water_review_service.py`, add import near existing service imports:

```python
from app.services.core_extraction_service import build_core_extraction_chunks
```

After chunk creation/caching is complete and before `cached_prerag`, insert:

```python
    core_selection = build_core_extraction_chunks(chunks, session_id, artifact_path)
    core_chunks = core_selection.chunks
    timings["pipeline_core_extraction_select_duration_ms"] = 0
    logger.info(
        "water_review_core_extraction_chunks session_id=%s mode=%s selected_count=%s input_count=%s",
        session_id,
        core_selection.mode,
        len(core_chunks),
        len(chunks),
    )
```

Replace:

```python
fallback_fields = extract_fields(chunks)
```

with:

```python
fallback_fields = extract_fields(core_chunks)
```

Replace:

```python
langextract_facts = [*table_facts, *run_langextract(chunks)]
```

with:

```python
langextract_facts = [*table_facts, *run_langextract(core_chunks)]
```

Do not change the later `run_rag_review(session_id, chunks, rules, ...)` call.

- [ ] **Step 4: Run focused tests**

Run:

```bash
cd backend
uv run pytest tests/test_core_extraction_service.py tests/test_water_review_extraction.py tests/test_langextract_service.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/water_review_service.py backend/tests/test_core_extraction_service.py
git commit -m "feat: use core chunks for field extraction"
```

---

### Task 5: Integration Verification And Cleanup

**Files:**
- Modify only files already touched by Tasks 1-4 if verification exposes issues.

- [ ] **Step 1: Run target backend tests from the spec**

Run:

```bash
cd backend
uv run pytest tests/test_core_extraction_service.py tests/test_water_review_extraction.py tests/test_langextract_service.py tests/test_earthwork_audit_service.py tests/test_rag_query_relevance.py -q
```

Expected: PASS.

- [ ] **Step 2: Run Python compile check**

Run:

```bash
cd backend
uv run python -m compileall app
```

Expected: command exits 0.

- [ ] **Step 3: Inspect changed files**

Run:

```bash
git diff -- backend/app/services/core_extraction_service.py backend/app/services/water_review_extraction.py backend/app/services/langextract_service.py backend/app/services/water_review_service.py backend/tests/test_core_extraction_service.py backend/tests/test_water_review_extraction.py backend/tests/test_langextract_service.py
```

Expected: diff only contains focused core extraction changes.

- [ ] **Step 4: Final commit if verification required fixes**

If Step 1 or Step 2 required fixes, commit only the relevant files:

```bash
git add backend/app/services/core_extraction_service.py backend/app/services/water_review_extraction.py backend/app/services/langextract_service.py backend/app/services/water_review_service.py backend/tests/test_core_extraction_service.py backend/tests/test_water_review_extraction.py backend/tests/test_langextract_service.py
git commit -m "fix: stabilize core extraction pipeline"
```

If no fixes were needed after Task 4, skip this commit.

---

## Self-Review Notes

- Spec coverage: Tasks 1 and 4 implement retrieval-first core chunk selection and trace artifact; Task 2 implements core fallback fields; Task 3 implements LangExtract narrowing; Task 5 verifies target behavior.
- Scope: Backend-only. No frontend, API schema, MinerU parser, or review-rule expansion.
- Dirty worktree boundary: every commit command names only files owned by this plan. Existing unrelated modifications must remain untouched.
