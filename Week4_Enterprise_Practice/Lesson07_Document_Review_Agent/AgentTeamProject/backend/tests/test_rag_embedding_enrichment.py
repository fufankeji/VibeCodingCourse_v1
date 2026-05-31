import json
import sys

from app.services import rag_service, water_review_service
from app.services.water_review_service import ReviewChunk


def test_mineru_chunks_keep_structure_for_embedding_and_location_metadata(tmp_path):
    source = tmp_path / "mineru.json"
    source.write_text(
        json.dumps(
            {
                "pdf_info": [
                    {
                        "page_idx": 2,
                        "page_size": [595, 841],
                        "para_blocks": [
                            {
                                "type": "table",
                                "sub_type": "table_with_caption",
                                "bbox": [60, 120, 520, 260],
                                "index": 7,
                                "html": (
                                    "<table>"
                                    "<tr><th>位置</th><th>结论</th></tr>"
                                    "<tr><td>弃渣场</td><td>本项目不存在弃渣场</td></tr>"
                                    "</table>"
                                ),
                                "blocks": [
                                    {
                                        "type": "table_caption",
                                        "bbox": [60, 100, 520, 118],
                                        "lines": [
                                            {
                                                "bbox": [60, 100, 520, 118],
                                                "spans": [
                                                    {
                                                        "type": "text",
                                                        "bbox": [60, 100, 520, 118],
                                                        "content": "表 5-1 弃渣场设置分析",
                                                    }
                                                ],
                                            }
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    blocks = water_review_service._parse_mineru_json(source)
    chunks = water_review_service.build_chunks(blocks)

    assert blocks[0].page_size == [595.0, 841.0]
    assert blocks[0].mineru_index == 7
    assert blocks[0].mineru_sub_type == "table_with_caption"
    assert blocks[0].child_types == ["table_caption"]
    assert blocks[0].span_types == ["text"]

    chunk = chunks[0]
    assert chunk.text == "表 5-1 弃渣场设置分析"
    assert "表 5-1 弃渣场设置分析" in chunk.embedding_text
    assert "本项目不存在弃渣场" in chunk.embedding_text
    assert "表格HTML文本" not in chunk.embedding_text
    assert "块类型" not in chunk.embedding_text
    assert "第3页" not in chunk.embedding_text
    assert chunk.bbox_list[0]["page_width"] == 595.0
    assert chunk.bbox_list[0]["page_height"] == 841.0
    assert chunk.bbox_list[0]["mineru_index"] == 7
    assert chunk.metadata["block_types"] == ["table"]
    assert chunk.metadata["block_sub_types"] == ["table_with_caption"]
    assert chunk.metadata["page_sizes"] == {"3": [595.0, 841.0]}
    assert chunk.metadata["has_table"] is True


def test_chroma_rebuild_embeds_enriched_text_but_stores_display_text():
    chunk = ReviewChunk(
        chunk_id="chunk-0001",
        text="表 5-1 弃渣场设置分析",
        section="5.1.2 水土保持分析与评价",
        page_range=[79, 79],
        bbox_list=[
            {
                "block_id": "p79-b7",
                "page": 79,
                "bbox": [60, 120, 520, 260],
                "page_width": 595,
                "page_height": 841,
            }
        ],
        table_refs=["p79-b7"],
        metadata={
            "block_ids": ["p79-b7"],
            "block_types": ["table"],
            "block_sub_types": ["table_with_caption"],
            "mineru_indexes": [7],
            "child_types": ["table_caption", "table_body"],
            "span_types": ["text"],
            "page_sizes": {"79": [595, 841]},
            "has_table": True,
            "has_image": False,
        },
        char_start=0,
        char_end=13,
        embedding_text="表 5-1 弃渣场设置分析\n本项目不存在弃渣场。",
    )
    embedder = _RecordingEmbedder()
    collection = _RecordingCollection()
    store = rag_service.ChromaChunkStore.__new__(rag_service.ChromaChunkStore)
    store.collection = collection
    store.client = _UnusedClient()
    store.collection_name = "test"
    store.embedder = embedder

    store.rebuild([chunk])

    assert embedder.texts == [chunk.embedding_text]
    assert collection.upsert_payload["documents"] == [chunk.text]
    metadata = collection.upsert_payload["metadatas"][0]
    assert metadata["bbox_json"]
    assert json.loads(metadata["block_types_json"]) == ["table"]
    assert json.loads(metadata["page_sizes_json"]) == {"79": [595, 841]}
    assert metadata["embedding_enriched"] is True
    assert metadata["embedding_text_sha1"]


def test_chroma_rebuild_uses_content_hash_not_only_ids_and_dimension(monkeypatch):
    monkeypatch.setattr(rag_service.settings, "siliconflow_embedding_dimensions", 2)
    chunk = ReviewChunk(
        chunk_id="chunk-0001",
        text="原始展示文本",
        section="1 项目概况",
        page_range=[1, 1],
        bbox_list=[],
        table_refs=[],
        metadata={},
        char_start=0,
        char_end=6,
        embedding_text="新的向量文本",
    )
    embedder = _RecordingEmbedder()
    collection = _RecordingCollection(
        existing_ids=["chunk-0001"],
        existing_metadatas=[{"index_content_hash": "stale"}],
        existing_embeddings=[[1.0, 0.0]],
    )
    store = rag_service.ChromaChunkStore.__new__(rag_service.ChromaChunkStore)
    store.collection = collection
    store.client = _UnusedClient()
    store.collection_name = "test"
    store.embedder = embedder

    store.rebuild([chunk])

    assert collection.deleted_ids == ["chunk-0001"]
    assert embedder.texts == ["新的向量文本"]
    assert collection.upsert_payload["metadatas"][0]["index_content_hash"]


def test_review_issue_locations_follow_evidence_window(monkeypatch):
    monkeypatch.setattr(rag_service, "execute_rule_precheck", lambda *args, **kwargs: {"status": "needs_review"})
    monkeypatch.setattr(
        rag_service,
        "_call_deepseek_adjudicator",
        lambda *args, **kwargs: {
            "risk_level": "MEDIUM",
            "confidence": 80,
            "issue_desc": "需要复核",
            "actual_value": "见证据窗口",
            "expected_value": "规则要求",
            "fix_suggestion": "补充说明",
            "conclusion_type": "needs_review",
        },
    )
    match = {
        "chunk_id": "chunk-0001",
        "document": "核心片段",
        "metadata": {
            "page_start": 10,
            "chunk_index": 0,
            "bbox_json": json.dumps([{"block_id": "core", "page": 10, "bbox": [1, 1, 2, 2]}], ensure_ascii=False),
            "block_ids_json": json.dumps(["core"], ensure_ascii=False),
            "evidence_window_text": "窗口片段",
            "evidence_window_bbox_json": json.dumps(
                [{"block_id": "window", "page": 10, "bbox": [3, 3, 4, 4]}],
                ensure_ascii=False,
            ),
            "evidence_window_block_ids_json": json.dumps(["window"], ensure_ascii=False),
        },
        "score": 0.8,
    }

    issue = rag_service._adjudicate_rule("session", {"rule_id": "R1", "rule_name": "规则"}, [match], {})
    reasoning = json.loads(issue["ai_reasoning"])

    assert issue["clause_text"] == "窗口片段"
    assert reasoning["evidence_nodes"] == ["window"]
    assert reasoning["source_bbox_list"][0]["block_id"] == "window"


def test_three_layer_chunking_keeps_atomic_sections_semantic_chunks_and_windows():
    blocks = [
        _block("p1-b1", "5 水土保持分析与评价", "title", 1),
        _block("p1-b2", "5.1 主体工程选址分析", "title", 1),
        _block("p1-b3", "项目选址不涉及水土流失重点治理区。", "paragraph", 1),
        _block("p1-b4", "项目周边无崩塌滑坡危险区。", "paragraph", 1),
        _block("p2-b1", "5.2 弃渣场设置分析", "title", 2),
        _block("p2-b2", "本项目不存在弃渣（土、石）场。", "paragraph", 2),
    ]
    section_stack = []
    for index, block in enumerate(blocks):
        if block.type == "title":
            section_stack = water_review_service._update_section_stack(section_stack, block.text)
        block.parent_section = water_review_service._section_path(section_stack)
        block.section_hint = block.parent_section
        block.atomic_index = index

    chunks = water_review_service.build_chunks(blocks, max_chars=80)

    semantic_chunks = [chunk for chunk in chunks if chunk.metadata["chunk_layer"] == "semantic"]
    assert len(semantic_chunks) >= 2
    assert semantic_chunks[0].section == "5 水土保持分析与评价 / 5.1 主体工程选址分析"
    assert "5.2 弃渣场设置分析" not in semantic_chunks[0].text
    assert semantic_chunks[-1].section == "5 水土保持分析与评价 / 5.2 弃渣场设置分析"
    assert semantic_chunks[-1].metadata["atomic_block_ids"] == ["p2-b1", "p2-b2"]
    assert "p1-b4" in semantic_chunks[-1].metadata["evidence_window_block_ids"]
    assert "本项目不存在弃渣" in semantic_chunks[-1].metadata["evidence_window_text"]


def test_table_html_builds_table_row_chunks_for_precise_retrieval():
    block = _block("p79-b7", "表 5-1 弃渣场设置分析", "table", 79)
    block.html = (
        "<table>"
        "<tr><th>位置</th><th>结论</th></tr>"
        "<tr><td>弃渣场</td><td>本项目不存在弃渣场</td></tr>"
        "<tr><td>取土场</td><td>本项目不存在取土场</td></tr>"
        "</table>"
    )
    block.caption = "表 5-1 弃渣场设置分析"
    block.parent_section = "5.1.2 水土保持分析与评价 / 弃渣场设置分析"
    block.section_hint = block.parent_section

    chunks = water_review_service.build_chunks([block])

    row_chunks = [chunk for chunk in chunks if chunk.metadata["chunk_layer"] == "table_row"]
    assert len(row_chunks) == 2
    assert row_chunks[0].metadata["parent_chunk_id"] == chunks[0].chunk_id
    assert "位置：弃渣场" in row_chunks[0].embedding_text
    assert "结论：本项目不存在弃渣场" in row_chunks[0].embedding_text
    assert row_chunks[0].table_refs == ["p79-b7"]


def test_low_value_cost_appendix_table_does_not_emit_row_chunks():
    block = _block("p168-b2", "工程单价汇总表 附表 1", "table", 168)
    block.html = (
        "<table>"
        "<tr><th>单价名称</th><th>人工费</th><th>材料费</th></tr>"
        "<tr><td>土地整治</td><td>292.22</td><td>339.00</td></tr>"
        "</table>"
    )
    block.caption = "工程单价汇总表 附表 1"
    block.parent_section = "水土保持方案部分投资概算附表"
    block.section_hint = block.parent_section

    chunks = water_review_service.build_chunks([block])

    assert [chunk.metadata["chunk_layer"] for chunk in chunks] == ["semantic"]


def test_chroma_store_deletes_stale_session_collections(monkeypatch, tmp_path):
    client = _RecordingClient(
        [
            "water_review_session-a_legacy",
            _CollectionName("water_review_session-a_current"),
            "water_review_other_legacy",
        ]
    )
    monkeypatch.setattr(rag_service.settings, "siliconflow_embedding_model", "model")
    monkeypatch.setattr(rag_service.settings, "siliconflow_embedding_dimensions", 2)
    monkeypatch.setattr(
        rag_service.hashlib,
        "sha1",
        lambda data: _FakeHash("current") if b":v4" in data else _FakeHash("legacy"),
    )
    monkeypatch.setitem(sys.modules, "chromadb", _ChromadbModule(client))

    store = rag_service.ChromaChunkStore(tmp_path, "session-a", _RecordingEmbedder())

    assert store.collection_name == "water_review_session-a_current"
    assert client.deleted == ["water_review_session-a_legacy"]
    assert client.created == ["water_review_session-a_current"]


class _RecordingEmbedder:
    def __init__(self):
        self.texts: list[str] = []

    def embed_texts(self, texts: list[str], batch_size: int = 32) -> list[list[float]]:
        self.texts = texts
        return [[1.0, 0.0] for _ in texts]


class _RecordingCollection:
    def __init__(
        self,
        existing_ids: list[str] | None = None,
        existing_metadatas: list[dict] | None = None,
        existing_embeddings: list[list[float]] | None = None,
    ):
        self.upsert_payload = {}
        self.deleted_ids: list[str] = []
        self.existing_ids = existing_ids or []
        self.existing_metadatas = existing_metadatas or []
        self.existing_embeddings = existing_embeddings or []

    def get(self, *args, **kwargs):
        if kwargs.get("include") == ["embeddings"]:
            return {"embeddings": self.existing_embeddings}
        if kwargs.get("include") == ["metadatas"]:
            return {"ids": self.existing_ids, "metadatas": self.existing_metadatas}
        return {"ids": self.existing_ids}

    def delete(self, ids):
        self.deleted_ids.extend(ids)

    def upsert(self, **kwargs):
        self.upsert_payload = kwargs


class _UnusedClient:
    def delete_collection(self, name):
        raise AssertionError(f"unexpected delete_collection: {name}")


class _RecordingClient:
    def __init__(self, collection_names):
        self.collection_names = collection_names
        self.deleted: list[str] = []
        self.created: list[str] = []

    def list_collections(self):
        return self.collection_names

    def delete_collection(self, name):
        self.deleted.append(name)

    def get_or_create_collection(self, name, metadata):
        self.created.append(name)
        return _RecordingCollection()


class _CollectionName:
    def __init__(self, name):
        self.name = name


class _ChromadbModule:
    def __init__(self, client):
        self._client = client

    def PersistentClient(self, path):
        return self._client


class _FakeHash:
    def __init__(self, value):
        self.value = value

    def hexdigest(self):
        return self.value


def _block(block_id: str, text: str, block_type: str, page: int) -> water_review_service.ParsedBlock:
    return water_review_service.ParsedBlock(
        block_id=block_id,
        page=page,
        bbox=[10.0, 20.0, 100.0, 40.0],
        text=text,
        type=block_type,
        section_hint="",
        char_start=0,
        char_end=len(text),
        page_size=[595.0, 841.0],
    )
