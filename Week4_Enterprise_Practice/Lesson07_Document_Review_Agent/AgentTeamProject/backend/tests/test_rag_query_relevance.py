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
