"""Three-layer chunk construction for water review documents."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

from app.services.water_review_models import (
    EVIDENCE_WINDOW_BLOCK_RADIUS,
    SEMANTIC_CHUNK_MAX_CHARS,
    SEMANTIC_CHUNK_OVERLAP_BLOCKS,
    TABLE_ROW_EXCLUDE_HINTS,
    TABLE_ROW_INCLUDE_KEYWORDS,
    TABLE_ROW_MAX_ROWS_PER_TABLE,
    ParsedBlock,
    ReviewChunk,
)
from app.services.water_review_utils import (
    _append_document_line,
    _html_to_text,
    _truncate_for_embedding,
    _unique_strings,
)

def build_chunks(blocks: list[ParsedBlock], max_chars: int = SEMANTIC_CHUNK_MAX_CHARS) -> list[ReviewChunk]:
    chunks: list[ReviewChunk] = []
    current: list[ParsedBlock] = []
    block_positions = {block.block_id: index for index, block in enumerate(blocks)}

    def next_chunk_id() -> str:
        return f"chunk-{len(chunks) + 1:04d}"

    def flush() -> None:
        nonlocal current
        core_blocks = [block for block in current if _block_document_text(block)]
        if not core_blocks:
            current = []
            return
        chunk = _semantic_chunk_from_blocks(next_chunk_id(), core_blocks, blocks, block_positions)
        if not chunk.text.strip():
            current = []
            return
        chunks.append(chunk)
        for table_block in [block for block in core_blocks if block.html and _should_emit_table_row_chunks(block)]:
            for row_text in _table_row_texts(table_block):
                chunks.append(_table_row_chunk(next_chunk_id(), table_block, row_text, chunk.chunk_id))
        current = []

    for block in blocks:
        if block.type == "title":
            if any(item.type != "title" and _block_document_text(item) for item in current):
                flush()
            current.append(block)
            continue
        projected_len = sum(_block_semantic_size(b) for b in current) + _block_semantic_size(block)
        if current and _block_section(current[-1]) != _block_section(block):
            flush()
        elif current and projected_len > max_chars:
            overlap = _overlap_blocks(current)
            flush()
            current.extend(overlap)
        current.append(block)
    flush()
    return chunks

def _block_anchor(block: ParsedBlock) -> dict[str, Any]:
    anchor: dict[str, Any] = {
        "block_id": block.block_id,
        "page": block.page,
        "bbox": block.bbox,
    }
    if len(block.page_size) >= 2:
        anchor["page_width"] = block.page_size[0]
        anchor["page_height"] = block.page_size[1]
    if block.mineru_index is not None:
        anchor["mineru_index"] = block.mineru_index
    if block.type:
        anchor["block_type"] = block.type
    if block.parent_section:
        anchor["parent_section"] = block.parent_section
    return anchor


def _semantic_chunk_from_blocks(
    chunk_id: str,
    core_blocks: list[ParsedBlock],
    all_blocks: list[ParsedBlock],
    block_positions: dict[str, int],
) -> ReviewChunk:
    section = _semantic_chunk_section(core_blocks)
    text = _semantic_chunk_display_text(core_blocks, section)
    window_blocks = _evidence_window_blocks(core_blocks, all_blocks, block_positions)
    pages = sorted({block.page for block in core_blocks})
    metadata = _chunk_structure_metadata(core_blocks)
    metadata.update(
        {
            "chunk_layer": "semantic",
            "parent_section": section,
            "atomic_block_ids": [block.block_id for block in core_blocks],
            "evidence_window_block_ids": [block.block_id for block in window_blocks],
            "evidence_window_text": _semantic_chunk_display_text(window_blocks, section),
            "evidence_window_bbox_list": [_block_anchor(block) for block in window_blocks if block.bbox],
        }
    )
    return ReviewChunk(
        chunk_id=chunk_id,
        text=text,
        section=section,
        page_range=[pages[0], pages[-1]] if pages else [1, 1],
        bbox_list=[_block_anchor(block) for block in core_blocks if block.bbox],
        table_refs=[block.block_id for block in core_blocks if block.type in {"table", "cell"} or block.html],
        metadata=metadata,
        char_start=core_blocks[0].char_start,
        char_end=core_blocks[-1].char_end,
        embedding_text=_build_chunk_embedding_text(core_blocks, section, text),
    )


def _table_row_chunk(chunk_id: str, table_block: ParsedBlock, row_text: str, parent_chunk_id: str) -> ReviewChunk:
    section = _block_section(table_block)
    text = "\n".join(_unique_strings([section, table_block.caption, row_text]))
    metadata = _chunk_structure_metadata([table_block])
    metadata.update(
        {
            "chunk_layer": "table_row",
            "parent_section": section,
            "parent_chunk_id": parent_chunk_id,
            "atomic_block_ids": [table_block.block_id],
            "evidence_window_block_ids": [table_block.block_id],
            "evidence_window_text": text,
            "evidence_window_bbox_list": [_block_anchor(table_block)] if table_block.bbox else [],
        }
    )
    return ReviewChunk(
        chunk_id=chunk_id,
        text=text,
        section=section,
        page_range=[table_block.page, table_block.page],
        bbox_list=[_block_anchor(table_block)] if table_block.bbox else [],
        table_refs=[table_block.block_id],
        metadata=metadata,
        char_start=table_block.char_start,
        char_end=table_block.char_end,
        embedding_text=text,
    )


def _chunk_structure_metadata(blocks: list[ParsedBlock]) -> dict[str, Any]:
    page_sizes: dict[str, list[float]] = {}
    for block in blocks:
        if len(block.page_size) >= 2:
            page_sizes[str(block.page)] = block.page_size[:2]
    return {
        "block_ids": [b.block_id for b in blocks],
        "block_types": _unique_strings([b.type for b in blocks]),
        "block_sub_types": _unique_strings([b.mineru_sub_type for b in blocks if b.mineru_sub_type]),
        "mineru_indexes": [b.mineru_index for b in blocks if b.mineru_index is not None],
        "child_types": _unique_strings(item for b in blocks for item in b.child_types),
        "span_types": _unique_strings(item for b in blocks for item in b.span_types),
        "page_sizes": page_sizes,
        "has_table": any(b.type == "table" or bool(b.html) for b in blocks),
        "has_image": any(b.type == "image" or bool(b.image_path) for b in blocks),
        "captions": _unique_strings([b.caption for b in blocks if b.caption]),
    }


def _build_chunk_embedding_text(blocks: list[ParsedBlock], section: str, display_text: str) -> str:
    lines: list[str] = []
    if section != "未识别章节":
        _append_document_line(lines, section)
    for block in blocks:
        _append_document_line(lines, _block_document_text(block))
        if block.html:
            table_text = _html_to_text(block.html)
            _append_document_line(lines, _truncate_for_embedding(table_text))
    return "\n".join(lines).strip() or display_text


def _semantic_chunk_display_text(blocks: list[ParsedBlock], section: str) -> str:
    lines: list[str] = []
    if section != "未识别章节":
        _append_document_line(lines, section)
    for block in blocks:
        _append_document_line(lines, _block_document_text(block))
    return "\n".join(lines).strip()


def _block_document_text(block: ParsedBlock) -> str:
    text = block.text.strip()
    if block.image_path and text == block.image_path.strip():
        return ""
    if block.html and len(text) > 900:
        return "\n".join(_unique_strings([block.caption, _truncate_for_embedding(text, 600)]))
    return text


def _block_semantic_size(block: ParsedBlock) -> int:
    size = len(_block_document_text(block))
    if block.html:
        table_text = _html_to_text(block.html)
        if table_text and table_text not in block.text:
            size += min(len(table_text), 900)
    return size


def _block_section(block: ParsedBlock) -> str:
    return block.parent_section or block.section_hint or "未识别章节"


def _semantic_chunk_section(blocks: list[ParsedBlock]) -> str:
    for block in reversed(blocks):
        if block.type != "title" and _block_section(block) != "未识别章节":
            return _block_section(block)
    for block in reversed(blocks):
        if _block_section(block) != "未识别章节":
            return _block_section(block)
    return "未识别章节"


def _overlap_blocks(blocks: list[ParsedBlock]) -> list[ParsedBlock]:
    candidates = [block for block in blocks if block.type != "title" and _block_document_text(block)]
    return candidates[-SEMANTIC_CHUNK_OVERLAP_BLOCKS:]


def _evidence_window_blocks(
    core_blocks: list[ParsedBlock],
    all_blocks: list[ParsedBlock],
    block_positions: dict[str, int],
) -> list[ParsedBlock]:
    positions = [block_positions[block.block_id] for block in core_blocks if block.block_id in block_positions]
    if not positions:
        return core_blocks
    start = max(0, min(positions) - EVIDENCE_WINDOW_BLOCK_RADIUS)
    end = min(len(all_blocks) - 1, max(positions) + EVIDENCE_WINDOW_BLOCK_RADIUS)
    window = all_blocks[start : end + 1]
    section = _block_section(core_blocks[0])
    section_titles = [
        block
        for block in all_blocks[: min(positions)]
        if block.type == "title" and block.text and block.text in section
    ]
    return _unique_blocks([*section_titles[-3:], *window])


def _unique_blocks(blocks: list[ParsedBlock]) -> list[ParsedBlock]:
    seen: set[str] = set()
    result: list[ParsedBlock] = []
    for block in blocks:
        if block.block_id in seen:
            continue
        seen.add(block.block_id)
        result.append(block)
    return result


def _table_row_texts(block: ParsedBlock) -> list[str]:
    rows = _html_table_rows(block.html)
    if not rows:
        return []
    headers = rows[0] if _looks_like_header_row(rows[0]) else []
    data_rows = rows[1:] if headers else rows
    result: list[str] = []
    for row in data_rows:
        cells = [cell for cell in row if cell]
        if not cells:
            continue
        if headers and len(headers) == len(cells):
            result.append("；".join(f"{headers[index]}：{cell}" for index, cell in enumerate(cells)))
        else:
            result.append("；".join(cells))
    return _unique_strings(result)[:TABLE_ROW_MAX_ROWS_PER_TABLE]


def _html_table_rows(html: str) -> list[list[str]]:
    parser = _TableHTMLParser()
    parser.feed(html)
    return parser.rows


class _TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized == "tr":
            self._current_row = []
        elif normalized in {"td", "th"} and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
            cell = re.sub(r"\s+", " ", "".join(self._current_cell)).strip()
            self._current_row.append(cell)
            self._current_cell = None
        elif normalized == "tr" and self._current_row is not None:
            if any(cell.strip() for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = None


def _looks_like_header_row(row: list[str]) -> bool:
    joined = "".join(row)
    return bool(row) and any(keyword in joined for keyword in ["项目", "名称", "指标", "单位", "数量", "面积", "挖方", "填方", "位置", "结论"])


def _should_emit_table_row_chunks(block: ParsedBlock) -> bool:
    haystack = "\n".join([_block_section(block), block.caption, block.text, _html_to_text(block.html)])
    if any(keyword in haystack for keyword in TABLE_ROW_INCLUDE_KEYWORDS):
        return True
    if any(hint in haystack for hint in TABLE_ROW_EXCLUDE_HINTS):
        return False
    return False
