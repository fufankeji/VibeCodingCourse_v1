"""Structured fact extraction from MinerU table HTML."""

from __future__ import annotations

import hashlib
import re
from html.parser import HTMLParser
from typing import Any


EARTHWORK_FIELD_LABELS = {
    "excavation_volume": ["挖方", "开挖"],
    "fill_volume": ["填方", "回填"],
    "borrow_volume": ["借方", "借入", "取土量"],
    "spoil_volume": ["弃方", "弃土", "弃渣", "余方"],
}


def extract_table_facts(blocks: list[Any], chunks: list[Any]) -> list[dict[str, Any]]:
    """Extract grounded earthwork facts from parsed MinerU table blocks."""
    facts: list[dict[str, Any]] = []
    for block in blocks:
        if getattr(block, "type", "") != "table" or not getattr(block, "html", ""):
            continue
        rows = _parse_html_table(str(getattr(block, "html", "")))
        if not rows:
            continue
        chunk = _chunk_for_block(block, chunks)
        for field_name, value in _earthwork_values(rows).items():
            normalized_value, unit = _split_metric(value)
            if not normalized_value or not unit:
                continue
            facts.append(_fact(field_name, value, normalized_value, unit, block, chunk))
    return facts


def _earthwork_values(rows: list[list[str]]) -> dict[str, str]:
    values: dict[str, str] = {}
    for row_index, row in enumerate(rows):
        for cell_index, cell in enumerate(row):
            field_name = _field_for_label(cell)
            if not field_name or field_name in values:
                continue
            value = _metric_in_text(cell)
            if not value:
                value = _next_metric(row, cell_index + 1)
            unit = _unit_in_text(cell)
            if not value and row_index + 1 < len(rows) and cell_index < len(rows[row_index + 1]):
                value = _metric_in_text(rows[row_index + 1][cell_index])
                if not value and unit:
                    number = _number_in_text(rows[row_index + 1][cell_index])
                    value = f"{number}{unit}" if number else ""
            if value:
                values[field_name] = value
    return values


def _field_for_label(text: str) -> str:
    normalized = str(text or "").strip()
    for field_name, labels in EARTHWORK_FIELD_LABELS.items():
        if any(label in normalized for label in labels):
            return field_name
    return ""


def _next_metric(row: list[str], start_index: int) -> str:
    for cell in row[start_index:]:
        value = _metric_in_text(cell)
        if value:
            return value
    return ""


def _metric_in_text(text: str) -> str:
    match = re.search(r"-?\d+(?:\.\d+)?\s*(?:万m³|万m3|万方|m³|m3|方)", text, re.I)
    return match.group(0).replace(" ", "") if match else ""


def _unit_in_text(text: str) -> str:
    matches = re.findall(r"(万m³|万m3|万方|m³|m3|方)", text, re.I)
    return matches[-1] if matches else ""


def _number_in_text(text: str) -> str:
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return match.group(0) if match else ""


def _split_metric(value: str) -> tuple[str, str]:
    match = re.search(r"(-?\d+(?:\.\d+)?)\s*(万m³|万m3|万方|m³|m3|方)", value, re.I)
    if not match:
        return "", ""
    return match.group(1), match.group(2)


def _fact(
    field_name: str,
    value: str,
    normalized_value: str,
    unit: str,
    block: Any,
    chunk: Any | None,
) -> dict[str, Any]:
    block_id = str(getattr(block, "block_id", "") or "")
    chunk_id = str(getattr(chunk, "chunk_id", "") or "")
    digest = hashlib.sha1(f"{field_name}|{value}|{block_id}|{chunk_id}".encode()).hexdigest()[:10]
    page = int(getattr(block, "page", 1) or 1)
    bbox = getattr(block, "bbox", []) or []
    return {
        "fact_id": f"mineru-table-{digest}",
        "field_name": field_name,
        "value": value,
        "normalized_value": normalized_value,
        "unit": unit,
        "section": str(getattr(chunk, "section", "") or getattr(block, "section_hint", "") or ""),
        "chunk_id": chunk_id,
        "page_range": list(getattr(chunk, "page_range", []) or [page, page]),
        "source_text": str(getattr(block, "text", "") or value),
        "char_interval": {
            "start_pos": int(getattr(block, "char_start", 0) or 0),
            "end_pos": int(getattr(block, "char_end", 0) or 0),
        },
        "block_ids": [block_id] if block_id else [],
        "bbox_list": [{"block_id": block_id, "page": page, "bbox": bbox}] if block_id and bbox else [],
        "confidence": 96,
        "attributes": {"source": "mineru_table_html"},
    }


def _chunk_for_block(block: Any, chunks: list[Any]) -> Any | None:
    block_id = str(getattr(block, "block_id", "") or "")
    for chunk in chunks:
        table_refs = [str(item) for item in getattr(chunk, "table_refs", []) or []]
        if block_id and block_id in table_refs:
            return chunk
        metadata = getattr(chunk, "metadata", {}) or {}
        block_ids = [str(item) for item in metadata.get("block_ids", [])] if isinstance(metadata, dict) else []
        if block_id and block_id in block_ids:
            return chunk
    return None


def _parse_html_table(html: str) -> list[list[str]]:
    parser = _TableParser()
    parser.feed(html)
    return [[cell for cell in row if cell] for row in parser.rows if any(cell for cell in row)]


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag in {"td", "th"}:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._cell is not None:
            if self._row is not None:
                self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
