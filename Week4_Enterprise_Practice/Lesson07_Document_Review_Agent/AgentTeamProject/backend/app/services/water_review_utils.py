"""Small shared helpers for water review modules."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.services.water_review_models import SECTION_KEYWORDS


def _caption_from_text(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines[:3]:
        if re.match(r"^(表|图)\s*[\d一二三四五六七八九十.-]+", line) or "表" in line[:8] or "图" in line[:8]:
            return line[:120]
    return ""


def _replace_section_level(section_stack: list[tuple[int, str]], level: int, title: str) -> list[tuple[int, str]]:
    if not title:
        return section_stack
    kept = [(item_level, item_title) for item_level, item_title in section_stack if item_level < level]
    return [*kept, (level, title)]


def _heading_level(title: str) -> int:
    stripped = title.strip()
    if re.match(r"^第[一二三四五六七八九十\d]+章", stripped):
        return 1
    match = re.match(r"^(\d+(?:\.\d+)*)", stripped)
    if match:
        return min(match.group(1).count(".") + 1, 5)
    if re.match(r"^[一二三四五六七八九十]+[、.．]", stripped):
        return 2
    if re.match(r"^[（(][一二三四五六七八九十\d]+[）)]", stripped):
        return 3
    return 2


def _section_path(section_stack: list[tuple[int, str]]) -> str:
    return " / ".join(title for _, title in section_stack)


def _append_document_line(lines: list[str], text: str) -> None:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return
    if any(normalized == existing or normalized in existing for existing in lines):
        return
    lines.append(normalized)


def _truncate_for_embedding(text: str, limit: int = 900) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _classify_block(text: str) -> str:
    stripped = text.strip()
    if len(stripped) <= 40 and re.match(r"^([一二三四五六七八九十]+[、.．]|第[一二三四五六七八九十\d]+章|\d+(\.\d+)*\s*)", stripped):
        return "title"
    if "|" in stripped or re.search(r"\b(合计|单位|面积|数量)\b", stripped):
        return "table" if len(stripped) > 60 else "paragraph"
    return "paragraph"


def _section_hint(text: str) -> str:
    for section, keywords in SECTION_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return section
    return ""


def _number_list(values: Any) -> list[float]:
    if not isinstance(values, list):
        return []
    result: list[float] = []
    for value in values:
        try:
            result.append(round(float(value), 2))
        except (TypeError, ValueError):
            continue
    return result


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _unique_strings(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _html_to_text(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()

def _detect_sections(text: str) -> list[str]:
    return [section for section, keywords in SECTION_KEYWORDS.items() if any(keyword in text for keyword in keywords)]

def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
