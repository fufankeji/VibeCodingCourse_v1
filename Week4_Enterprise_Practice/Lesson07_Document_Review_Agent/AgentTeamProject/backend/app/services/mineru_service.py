"""MinerU Open API integration for uploaded review documents."""

from __future__ import annotations

import copy
import io
import json
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.config import settings

MAX_ZIP_BYTES = 250 * 1024 * 1024
MAX_ZIP_MEMBERS = 5000
MAX_ZIP_MEMBER_BYTES = 100 * 1024 * 1024
MAX_MINERU_PAGES_PER_TASK = 200
ASSET_PATH_KEYS = {"image_path", "img_path", "table_image_path"}


class MinerUAPIError(RuntimeError):
    """Raised when MinerU parsing cannot produce a usable artifact."""

    def __init__(self, message: str, error_code: str = "MINERU_REMOTE_FAILED", *, timeout: bool = False) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.timeout = timeout


@dataclass
class MinerUParseArtifacts:
    json_path: Path | None = None
    markdown_path: Path | None = None
    zip_path: Path | None = None
    batch_id: str = ""
    task_id: str = ""
    zip_url: str = ""

    @property
    def best_parse_path(self) -> Path | None:
        return self.json_path or self.markdown_path


@dataclass(frozen=True)
class MinerUSegment:
    segment_index: int
    segment_count: int
    page_start: int
    page_end_requested: int
    page_offset: int
    page_ranges: str | None

    @property
    def part_name(self) -> str:
        return f"part-{self.segment_index:03d}"


def _plan_pdf_segments(page_count: int) -> list[MinerUSegment]:
    if page_count <= 0:
        raise MinerUAPIError("PDF page count must be greater than zero", "MINERU_PDF_PAGE_COUNT_INVALID")
    if page_count <= MAX_MINERU_PAGES_PER_TASK:
        return [
            MinerUSegment(
                segment_index=1,
                segment_count=1,
                page_start=1,
                page_end_requested=page_count,
                page_offset=0,
                page_ranges=None,
            )
        ]

    ranges: list[tuple[int, int]] = []
    start = 1
    while start <= page_count:
        end_requested = start + MAX_MINERU_PAGES_PER_TASK - 1
        ranges.append((start, end_requested))
        start = end_requested + 1

    segment_count = len(ranges)
    return [
        MinerUSegment(
            segment_index=index,
            segment_count=segment_count,
            page_start=start_page,
            page_end_requested=end_requested,
            page_offset=start_page - 1,
            page_ranges=f"{start_page}-{end_requested}",
        )
        for index, (start_page, end_requested) in enumerate(ranges, start=1)
    ]


def parse_file_to_artifacts(
    file_path: str,
    output_dir: Path,
    progress_callback: Any | None = None,
) -> MinerUParseArtifacts:
    token = _auth_token()
    if not token:
        raise MinerUAPIError("MINERU_TOKEN is required", "MINERU_TOKEN_MISSING")

    source = Path(file_path)
    if not source.exists():
        raise MinerUAPIError(f"Source file not found: {source}")

    output_dir.mkdir(parents=True, exist_ok=True)
    base_url = settings.mineru_base_url.rstrip("/")
    headers = _headers(token)
    source_page_count = _pdf_page_count(source) if source.suffix.lower() == ".pdf" else 1
    segments = _plan_pdf_segments(source_page_count)
    with httpx.Client(timeout=settings.mineru_request_timeout) as client:
        if len(segments) == 1 and segments[0].page_ranges is None:
            return _parse_single_mineru_task(client, base_url, headers, source, output_dir, progress_callback)

        if progress_callback:
            progress_callback("segmenting", {"segment_count": len(segments), "source_page_count": source_page_count})
        return _parse_segmented_pdf(client, base_url, headers, source, output_dir, source_page_count, segments, progress_callback)


def _parse_single_mineru_task(
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    source: Path,
    output_dir: Path,
    progress_callback: Any | None = None,
    *,
    segment: MinerUSegment | None = None,
) -> MinerUParseArtifacts:
    batch_id = _submit_local_file(client, base_url, headers, source, segment=segment)
    if progress_callback:
        progress_callback("uploaded", {"batch_id": batch_id, **_segment_progress(segment)})
    task = _wait_batch_result(client, base_url, headers, batch_id, progress_callback=progress_callback, segment=segment)
    zip_url = str(task.get("full_zip_url") or "").strip()
    if not zip_url:
        code = "MINERU_SEGMENT_ZIP_MISSING" if segment else "MINERU_RESULT_INVALID"
        raise MinerUAPIError("MinerU result did not include full_zip_url", code)
    if progress_callback:
        progress_callback(
            "downloading",
            {"batch_id": batch_id, "task_id": str(task.get("task_id") or ""), **_segment_progress(segment)},
        )
    response = client.get(zip_url, headers=headers)
    _raise_for_status(response)

    artifacts = extract_zip_artifacts(response.content, output_dir)
    artifacts.batch_id = batch_id
    artifacts.task_id = str(task.get("task_id") or "")
    artifacts.zip_url = zip_url
    if artifacts.best_parse_path is None:
        raise MinerUAPIError("MinerU zip did not contain usable Markdown or structured JSON", "MINERU_RESULT_INVALID")
    return artifacts


def _parse_segmented_pdf(
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    source: Path,
    output_dir: Path,
    source_page_count: int,
    segments: list[MinerUSegment],
    progress_callback: Any | None = None,
) -> MinerUParseArtifacts:
    segment_results: list[dict[str, Any]] = []
    for segment in segments:
        segment_dir = output_dir / "segments" / segment.part_name
        if progress_callback:
            progress_callback("polling", {"message": "MinerU segment started", **_segment_progress(segment)})
        started = time.monotonic()
        try:
            artifacts = _parse_single_mineru_task(
                client,
                base_url,
                headers,
                source,
                segment_dir,
                progress_callback,
                segment=segment,
            )
        except MinerUAPIError as exc:
            raise _segment_error(exc) from exc
        if not artifacts.json_path:
            raise MinerUAPIError(f"MinerU segment {segment.part_name} did not produce JSON", "MINERU_SEGMENT_JSON_MISSING")
        segment_results.append(
            {
                "segment": segment,
                "json_path": artifacts.json_path,
                "markdown_path": artifacts.markdown_path,
                "zip_path": artifacts.zip_path,
                "batch_id": artifacts.batch_id,
                "task_id": artifacts.task_id,
                "duration_ms": int((time.monotonic() - started) * 1000),
            }
        )

    return _merge_segment_artifacts(
        source_file_path=str(source),
        source_page_count=source_page_count,
        output_dir=output_dir,
        segments=segments,
        segment_results=segment_results,
    )


def _segment_progress(segment: MinerUSegment | None) -> dict[str, Any]:
    if not segment:
        return {}
    return {
        "segment_index": segment.segment_index,
        "segment_count": segment.segment_count,
        "page_ranges": segment.page_ranges,
        "page_start": segment.page_start,
        "page_end_requested": segment.page_end_requested,
    }


def _segment_error(exc: MinerUAPIError) -> MinerUAPIError:
    if exc.error_code == "MINERU_TIMEOUT":
        return MinerUAPIError(str(exc), "MINERU_SEGMENT_TIMEOUT", timeout=True)
    if exc.error_code in {
        "MINERU_AUTH_FAILED",
        "MINERU_RATE_LIMITED",
        "MINERU_TOKEN_MISSING",
        "MINERU_ZIP_TOO_LARGE",
        "MINERU_ZIP_UNSAFE",
        "MINERU_RESULT_INVALID",
    }:
        return MinerUAPIError(str(exc), exc.error_code, timeout=exc.timeout)
    if exc.error_code.startswith("MINERU_SEGMENT_"):
        return exc
    return MinerUAPIError(str(exc), "MINERU_SEGMENT_FAILED", timeout=exc.timeout)


def _pdf_page_count(source: Path) -> int:
    try:
        import fitz

        with fitz.open(source) as doc:
            return int(doc.page_count)
    except Exception as exc:
        raise MinerUAPIError(f"Unable to read PDF page count: {source}", "MINERU_PDF_PAGE_COUNT_INVALID") from exc


def extract_zip_artifacts(zip_bytes: bytes, output_dir: Path) -> MinerUParseArtifacts:
    if len(zip_bytes) > MAX_ZIP_BYTES:
        raise MinerUAPIError("MinerU zip exceeds size limit", "MINERU_ZIP_TOO_LARGE")
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / "mineru_result.zip"
    zip_path.write_bytes(zip_bytes)

    structured_jsons: list[dict[str, Any]] = []
    markdown_text = ""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
            members = zf.infolist()
            if len(members) > MAX_ZIP_MEMBERS:
                raise MinerUAPIError("MinerU zip has too many files", "MINERU_ZIP_TOO_LARGE")
            for member in members:
                if member.is_dir():
                    continue
                if member.file_size > MAX_ZIP_MEMBER_BYTES:
                    raise MinerUAPIError("MinerU zip member exceeds size limit", "MINERU_ZIP_TOO_LARGE")
                target = _safe_zip_member(output_dir, member.filename)
                name = member.filename
                lower = name.lower()
                member_bytes = zf.read(name)
                if target != zip_path:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(member_bytes)
                if lower.endswith(".json"):
                    candidate = _load_json_bytes(member_bytes)
                    if _is_structured_mineru_json(candidate):
                        structured_jsons.append(candidate)
                elif lower.endswith(".md") and (not markdown_text or Path(name).name == "full.md"):
                    markdown_text = member_bytes.decode("utf-8", errors="replace")
    except zipfile.BadZipFile as exc:
        raise MinerUAPIError("MinerU result is not a valid zip", "MINERU_RESULT_INVALID") from exc

    json_path = None
    if structured_jsons:
        structured_json = max(structured_jsons, key=_mineru_block_count)
        json_path = output_dir / "parsed.json"
        json_path.write_text(json.dumps(structured_json, ensure_ascii=False, indent=2), encoding="utf-8")

    markdown_path = None
    if markdown_text.strip():
        markdown_path = output_dir / "full.md"
        markdown_path.write_text(markdown_text, encoding="utf-8")

    return MinerUParseArtifacts(json_path=json_path, markdown_path=markdown_path, zip_path=zip_path)


def _merge_segment_artifacts(
    *,
    source_file_path: str,
    source_page_count: int,
    output_dir: Path,
    segments: list[MinerUSegment],
    segment_results: list[dict[str, Any]],
) -> MinerUParseArtifacts:
    merged: dict[str, Any] = {"pdf_info": []}
    merged_pages: list[dict[str, Any]] = []
    markdown_parts: list[str] = []
    manifest_segments: list[dict[str, Any]] = []

    for result in segment_results:
        segment = result["segment"]
        json_path = result.get("json_path")
        if not json_path:
            raise MinerUAPIError(f"MinerU segment {segment.part_name} did not produce JSON", "MINERU_SEGMENT_JSON_MISSING")
        try:
            raw = json.loads(Path(json_path).read_text(encoding="utf-8"))
        except Exception as exc:
            raise MinerUAPIError(f"MinerU segment {segment.part_name} JSON is invalid", "MINERU_MERGE_INVALID_JSON") from exc
        pages = raw.get("pdf_info") if isinstance(raw, dict) else None
        if not isinstance(pages, list) or not pages:
            raise MinerUAPIError(f"MinerU segment {segment.part_name} JSON missing pdf_info", "MINERU_SEGMENT_JSON_MISSING")
        if not merged_pages:
            merged = copy.deepcopy(raw)
            merged["pdf_info"] = []
        for local_order, page in enumerate(pages):
            if not isinstance(page, dict):
                raise MinerUAPIError(f"MinerU segment {segment.part_name} contains invalid page", "MINERU_MERGE_INVALID_JSON")
            page_copy = copy.deepcopy(page)
            page_copy["page_idx"] = segment.page_offset + local_order
            _rewrite_asset_paths(page_copy, f"segments/{segment.part_name}")
            merged_pages.append(page_copy)

        markdown_path = result.get("markdown_path")
        if markdown_path and Path(markdown_path).exists():
            markdown_parts.append(
                f"<!-- MinerU segment {segment.segment_index}/{segment.segment_count} pages "
                f"{segment.page_start}-{segment.page_end_requested} -->\n"
                + Path(markdown_path).read_text(encoding="utf-8")
            )
        manifest_segments.append(
            {
                "segment_index": segment.segment_index,
                "segment_count": segment.segment_count,
                "page_start": segment.page_start,
                "page_end_requested": segment.page_end_requested,
                "page_offset": segment.page_offset,
                "page_ranges": segment.page_ranges,
                "batch_id": result.get("batch_id") or "",
                "task_id": result.get("task_id") or "",
                "status": "succeeded",
                "page_count_returned": len(pages),
                "duration_ms": int(result.get("duration_ms") or 0),
                "zip_path": _relative_to_output(result.get("zip_path"), output_dir),
                "json_path": _relative_to_output(result.get("json_path"), output_dir),
                "markdown_path": _relative_to_output(result.get("markdown_path"), output_dir),
            }
        )

    merged_pages.sort(key=lambda page: int(page.get("page_idx", -1)))
    _validate_merged_pages(merged_pages, source_page_count)
    merged["pdf_info"] = merged_pages

    json_path = output_dir / "parsed.json"
    json_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path = output_dir / "full.md"
    markdown_path.write_text("\n\n".join(markdown_parts), encoding="utf-8")
    manifest_path = output_dir / "segment_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "source_file_path": source_file_path,
                "source_page_count": source_page_count,
                "segment_size": MAX_MINERU_PAGES_PER_TASK,
                "segments": manifest_segments,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return MinerUParseArtifacts(json_path=json_path, markdown_path=markdown_path)


def _rewrite_asset_paths(value: Any, prefix: str) -> None:
    if isinstance(value, dict):
        for key, item in list(value.items()):
            if key in ASSET_PATH_KEYS and isinstance(item, str) and item and not item.startswith(("http://", "https://", "/")):
                original_key = f"original_{key}"
                value.setdefault(original_key, item)
                value[key] = f"{prefix}/{item}"
            else:
                _rewrite_asset_paths(item, prefix)
    elif isinstance(value, list):
        for item in value:
            _rewrite_asset_paths(item, prefix)


def _validate_merged_pages(pages: list[dict[str, Any]], source_page_count: int) -> None:
    page_indexes = [page.get("page_idx") for page in pages]
    expected = list(range(source_page_count))
    if page_indexes != expected:
        raise MinerUAPIError(
            f"Merged MinerU pages are not continuous: expected 0..{source_page_count - 1}, "
            f"got {page_indexes[:5]}...{page_indexes[-5:]}",
            "MINERU_MERGE_PAGE_MISMATCH",
        )


def _relative_to_output(path_value: Any, output_dir: Path) -> str | None:
    if not path_value:
        return None
    path = Path(path_value)
    try:
        return str(path.relative_to(output_dir))
    except ValueError:
        return str(path)


def _auth_token() -> str:
    return settings.mineru_token.strip()


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "*/*",
    }


def _submit_local_file(
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    source: Path,
    *,
    segment: MinerUSegment | None = None,
) -> str:
    file_payload = {"name": source.name, "data_id": source.stem[:128]}
    if segment and segment.page_ranges:
        file_payload["page_ranges"] = segment.page_ranges
    payload = {
        "files": [file_payload],
        "model_version": settings.mineru_model_version,
        "enable_formula": settings.mineru_enable_formula,
        "enable_table": settings.mineru_enable_table,
        "language": settings.mineru_language,
    }
    response = client.post(f"{base_url}/file-urls/batch", headers=headers, json=payload)
    _raise_for_status(response)
    body = response.json()
    _ensure_success(body)
    data = body.get("data") or {}
    batch_id = str(data.get("batch_id") or "").strip()
    upload_urls = data.get("file_urls") or []
    if not batch_id or not upload_urls:
        raise MinerUAPIError("MinerU upload-url response is missing batch_id or file_urls", "MINERU_RESULT_INVALID")

    upload_response = client.put(str(upload_urls[0]), content=source.read_bytes())
    _raise_for_status(upload_response)
    return batch_id


def _wait_batch_result(
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    batch_id: str,
    progress_callback: Any | None = None,
    *,
    segment: MinerUSegment | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + settings.mineru_poll_timeout_seconds
    interval = max(1, settings.mineru_poll_interval_seconds)
    last_state = "pending"
    poll_started = time.monotonic()
    while time.monotonic() < deadline:
        response = client.get(f"{base_url}/extract-results/batch/{batch_id}", headers=headers)
        _raise_for_status(response)
        body = response.json()
        _ensure_success(body)
        results = _extract_results(body.get("data") or {})
        if results:
            task = results[0]
            last_state = str(task.get("state") or last_state)
            if progress_callback:
                progress_callback(
                    "polling",
                    {"batch_id": batch_id, "task_id": str(task.get("task_id") or ""), **_segment_progress(segment)},
                )
            if last_state == "done":
                if progress_callback:
                    progress_callback(
                        "polling",
                        {
                            "batch_id": batch_id,
                            "task_id": str(task.get("task_id") or ""),
                            "mineru_poll_duration_ms": int((time.monotonic() - poll_started) * 1000),
                            **_segment_progress(segment),
                        },
                    )
                return task
            if last_state == "failed":
                raise MinerUAPIError(str(task.get("err_msg") or "MinerU parsing failed"), "MINERU_REMOTE_FAILED")
        time.sleep(interval)
    raise MinerUAPIError(
        f"MinerU parsing timed out: batch_id={batch_id}, state={last_state}",
        "MINERU_TIMEOUT",
        timeout=True,
    )


def _extract_results(data: dict[str, Any]) -> list[dict[str, Any]]:
    raw = data.get("extract_result") or data.get("results") or []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        return [raw]
    return []


def _ensure_success(body: dict[str, Any]) -> None:
    if body.get("code") not in (0, "0", None):
        raise MinerUAPIError(str(body.get("msg") or "MinerU API returned an error"), "MINERU_REMOTE_FAILED")


def _load_json_bytes(payload: bytes) -> Any:
    try:
        return json.loads(payload.decode("utf-8"))
    except Exception:
        return None


def _is_structured_mineru_json(candidate: Any) -> bool:
    if not isinstance(candidate, dict):
        return False
    pdf_info = candidate.get("pdf_info")
    return isinstance(pdf_info, list) and bool(pdf_info)


def _mineru_block_count(candidate: dict[str, Any]) -> int:
    pages = candidate.get("pdf_info") or []
    return sum(len(page.get("para_blocks") or []) for page in pages if isinstance(page, dict))


def _safe_zip_member(output_dir: Path, member_name: str) -> Path:
    target = (output_dir / member_name).resolve()
    root = output_dir.resolve()
    if target != root and root not in target.parents:
        raise MinerUAPIError(f"Unsafe zip member path: {member_name}", "MINERU_ZIP_UNSAFE")
    return target


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status in {401, 403}:
            code = "MINERU_AUTH_FAILED"
        elif status == 429:
            code = "MINERU_RATE_LIMITED"
        else:
            code = "MINERU_REMOTE_FAILED"
        raise MinerUAPIError(str(exc), code) from exc
