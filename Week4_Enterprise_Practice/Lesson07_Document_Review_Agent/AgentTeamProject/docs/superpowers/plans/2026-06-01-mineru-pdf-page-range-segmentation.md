# MinerU PDF Page Range Segmentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MinerU page-range segmentation for PDFs over 200 pages, merge all segment JSON results into one continuous `parsed.json`, and keep the existing manual review-start flow intact.

**Architecture:** Keep `parse_file_to_artifacts(...)` as the worker-facing API. Internally route PDFs over 200 pages through segment orchestration that submits the same source PDF with `file.page_ranges`, extracts each segment to `segments/part-xxx/`, rewrites local segment page indexes into global page indexes, rewrites asset paths with segment prefixes, and writes final merged artifacts plus `segment_manifest.json`.

**Tech Stack:** Python 3.11, FastAPI service layer, SQLAlchemy worker state, PyMuPDF (`fitz`) for page count, httpx MinerU client, pytest.

---

## File Structure

- Modify: `backend/app/services/mineru_service.py`
  - Owns MinerU API calls, PDF page counting, segment generation, segment artifact extraction, JSON/Markdown merge, manifest writing, and segment error mapping.
- Modify: `backend/app/services/document_parse_worker.py`
  - Keeps worker API stable but records segment-aware progress payloads and final merged artifact paths.
- Modify: `backend/tests/test_mineru_service.py`
  - Adds unit tests for page range generation, payload `page_ranges`, segment merge, asset path rewriting, manifest output, and segment failures.
- Modify: `backend/tests/test_document_parse_worker.py`
  - Adds worker test that a segmented parse still marks the job `parsed` and records merged final paths.
- No DB migration in v1.
  - `DocumentParseJob.result_json_path` remains final merged `parsed.json`.
  - `DocumentParseJob.result_markdown_path` remains final merged `full.md`.
  - Segment details live in `segment_manifest.json`.

---

### Task 1: Add Page Range Planning Tests

**Files:**
- Modify: `backend/tests/test_mineru_service.py`
- Modify: `backend/app/services/mineru_service.py`

- [ ] **Step 1: Write failing tests for page range planning**

Append these tests to `backend/tests/test_mineru_service.py`:

```python
def test_plan_pdf_segments_keeps_small_pdf_single_segment():
    from app.services.mineru_service import _plan_pdf_segments

    segments = _plan_pdf_segments(200)

    assert len(segments) == 1
    assert segments[0].segment_index == 1
    assert segments[0].segment_count == 1
    assert segments[0].page_start == 1
    assert segments[0].page_end_requested == 200
    assert segments[0].page_offset == 0
    assert segments[0].page_ranges is None


def test_plan_pdf_segments_splits_pages_over_mineru_limit():
    from app.services.mineru_service import _plan_pdf_segments

    segments = _plan_pdf_segments(278)

    assert [segment.page_ranges for segment in segments] == ["1-200", "201-400"]
    assert [segment.page_offset for segment in segments] == [0, 200]
    assert [segment.page_start for segment in segments] == [1, 201]
    assert [segment.page_end_requested for segment in segments] == [200, 400]
    assert [segment.segment_count for segment in segments] == [2, 2]


def test_plan_pdf_segments_splits_401_pages_into_three_ranges():
    from app.services.mineru_service import _plan_pdf_segments

    segments = _plan_pdf_segments(401)

    assert [segment.page_ranges for segment in segments] == ["1-200", "201-400", "401-600"]
    assert [segment.page_offset for segment in segments] == [0, 200, 400]


def test_plan_pdf_segments_rejects_empty_pdf():
    from app.services.mineru_service import MinerUAPIError, _plan_pdf_segments

    try:
        _plan_pdf_segments(0)
    except MinerUAPIError as exc:
        assert exc.error_code == "MINERU_PDF_PAGE_COUNT_INVALID"
    else:
        raise AssertionError("empty PDF page count should fail")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend
uv run pytest tests/test_mineru_service.py::test_plan_pdf_segments_keeps_small_pdf_single_segment tests/test_mineru_service.py::test_plan_pdf_segments_splits_pages_over_mineru_limit tests/test_mineru_service.py::test_plan_pdf_segments_splits_401_pages_into_three_ranges tests/test_mineru_service.py::test_plan_pdf_segments_rejects_empty_pdf -q
```

Expected: FAIL because `_plan_pdf_segments` does not exist.

- [ ] **Step 3: Implement segment planning**

In `backend/app/services/mineru_service.py`, add constants and dataclass near the existing zip constants:

```python
MAX_MINERU_PAGES_PER_TASK = 200


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
```

Add this helper below `MinerUParseArtifacts`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd backend
uv run pytest tests/test_mineru_service.py::test_plan_pdf_segments_keeps_small_pdf_single_segment tests/test_mineru_service.py::test_plan_pdf_segments_splits_pages_over_mineru_limit tests/test_mineru_service.py::test_plan_pdf_segments_splits_401_pages_into_three_ranges tests/test_mineru_service.py::test_plan_pdf_segments_rejects_empty_pdf -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/mineru_service.py backend/tests/test_mineru_service.py
git commit -m "test: cover mineru pdf page range planning"
```

---

### Task 2: Add MinerU Upload Payload Support For `page_ranges`

**Files:**
- Modify: `backend/tests/test_mineru_service.py`
- Modify: `backend/app/services/mineru_service.py`

- [ ] **Step 1: Write failing test for `page_ranges` payload**

Append this test to `backend/tests/test_mineru_service.py`:

```python
def test_submit_local_file_includes_page_ranges_when_present(tmp_path):
    from app.services.mineru_service import MinerUSegment, _submit_local_file

    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    captured_payload = {}
    uploaded = {"called": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            captured_payload.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "batch_id": "batch-201-400",
                        "file_urls": ["https://upload.example/part"],
                    },
                },
            )
        if request.method == "PUT":
            uploaded["called"] = True
            return httpx.Response(200)
        return httpx.Response(404)

    segment = MinerUSegment(
        segment_index=2,
        segment_count=2,
        page_start=201,
        page_end_requested=400,
        page_offset=200,
        page_ranges="201-400",
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))

    batch_id = _submit_local_file(client, "https://mineru.example/api/v4", {"Authorization": "Bearer test"}, source, segment=segment)

    assert batch_id == "batch-201-400"
    assert uploaded["called"] is True
    assert captured_payload["files"][0]["page_ranges"] == "201-400"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
uv run pytest tests/test_mineru_service.py::test_submit_local_file_includes_page_ranges_when_present -q
```

Expected: FAIL because `_submit_local_file` does not accept `segment`.

- [ ] **Step 3: Update `_submit_local_file` signature and payload**

Change `_submit_local_file` in `backend/app/services/mineru_service.py` to:

```python
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
```

Keep the existing single-file caller working by not passing `segment`.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd backend
uv run pytest tests/test_mineru_service.py::test_submit_local_file_includes_page_ranges_when_present -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/mineru_service.py backend/tests/test_mineru_service.py
git commit -m "feat: support mineru page range upload payload"
```

---

### Task 3: Add Segment JSON Merge Tests And Implementation

**Files:**
- Modify: `backend/tests/test_mineru_service.py`
- Modify: `backend/app/services/mineru_service.py`

- [ ] **Step 1: Write failing tests for segment JSON and asset merge**

Append these tests to `backend/tests/test_mineru_service.py`:

```python
def test_merge_segment_json_rewrites_page_indexes_and_asset_paths(tmp_path):
    from app.services.mineru_service import MinerUSegment, _merge_segment_artifacts

    segments = [
        MinerUSegment(1, 2, 1, 200, 0, "1-200"),
        MinerUSegment(2, 2, 201, 400, 200, "201-400"),
    ]
    part1 = tmp_path / "segments" / "part-001"
    part2 = tmp_path / "segments" / "part-002"
    part1.mkdir(parents=True)
    part2.mkdir(parents=True)
    (part1 / "parsed.json").write_text(
        json.dumps({"pdf_info": [{"page_idx": 0, "para_blocks": [{"type": "image", "image_path": "images/a.jpg"}]}]}),
        encoding="utf-8",
    )
    (part2 / "parsed.json").write_text(
        json.dumps(
            {
                "pdf_info": [
                    {"page_idx": 0, "para_blocks": [{"type": "image", "image_path": "images/a.jpg"}]},
                    {"page_idx": 1, "para_blocks": [{"type": "text", "lines": [{"spans": [{"content": "尾页"}]}]}]},
                ]
            }
        ),
        encoding="utf-8",
    )
    (part1 / "full.md").write_text("第一页\n", encoding="utf-8")
    (part2 / "full.md").write_text("尾页\n", encoding="utf-8")

    artifacts = _merge_segment_artifacts(
        source_file_path="/tmp/source.pdf",
        source_page_count=3,
        output_dir=tmp_path,
        segments=segments,
        segment_results=[
            {"segment": segments[0], "json_path": part1 / "parsed.json", "markdown_path": part1 / "full.md", "zip_path": part1 / "mineru_result.zip", "batch_id": "b1", "task_id": "t1", "duration_ms": 10},
            {"segment": segments[1], "json_path": part2 / "parsed.json", "markdown_path": part2 / "full.md", "zip_path": part2 / "mineru_result.zip", "batch_id": "b2", "task_id": "t2", "duration_ms": 20},
        ],
    )

    merged = json.loads(artifacts.json_path.read_text(encoding="utf-8"))
    assert [page["page_idx"] for page in merged["pdf_info"]] == [0, 1, 2]
    first_block = merged["pdf_info"][0]["para_blocks"][0]
    third_block = merged["pdf_info"][2]["para_blocks"][0]
    assert first_block["image_path"] == "segments/part-001/images/a.jpg"
    assert first_block["original_image_path"] == "images/a.jpg"
    assert third_block["image_path"] == "segments/part-002/images/a.jpg"
    assert third_block["original_image_path"] == "images/a.jpg"
    assert "MinerU segment 1/2 pages 1-200" in artifacts.markdown_path.read_text(encoding="utf-8")
    manifest = json.loads((tmp_path / "segment_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_page_count"] == 3
    assert [item["batch_id"] for item in manifest["segments"]] == ["b1", "b2"]


def test_merge_segment_json_rejects_page_count_mismatch(tmp_path):
    from app.services.mineru_service import MinerUAPIError, MinerUSegment, _merge_segment_artifacts

    segment = MinerUSegment(1, 1, 1, 200, 0, "1-200")
    part = tmp_path / "segments" / "part-001"
    part.mkdir(parents=True)
    (part / "parsed.json").write_text(json.dumps({"pdf_info": [{"page_idx": 0, "para_blocks": []}]}), encoding="utf-8")

    try:
        _merge_segment_artifacts(
            source_file_path="/tmp/source.pdf",
            source_page_count=2,
            output_dir=tmp_path,
            segments=[segment],
            segment_results=[
                {"segment": segment, "json_path": part / "parsed.json", "markdown_path": None, "zip_path": None, "batch_id": "b1", "task_id": "t1", "duration_ms": 10}
            ],
        )
    except MinerUAPIError as exc:
        assert exc.error_code == "MINERU_MERGE_PAGE_MISMATCH"
    else:
        raise AssertionError("page count mismatch should fail")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend
uv run pytest tests/test_mineru_service.py::test_merge_segment_json_rewrites_page_indexes_and_asset_paths tests/test_mineru_service.py::test_merge_segment_json_rejects_page_count_mismatch -q
```

Expected: FAIL because `_merge_segment_artifacts` does not exist.

- [ ] **Step 3: Implement merge helpers**

In `backend/app/services/mineru_service.py`, import `copy`:

```python
import copy
```

Add helpers below `extract_zip_artifacts(...)`:

```python
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
                f"<!-- MinerU segment {segment.segment_index}/{segment.segment_count} pages {segment.page_start}-{segment.page_end_requested} -->\n"
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
```

Add these helper functions:

```python
ASSET_PATH_KEYS = {"image_path", "img_path", "table_image_path"}


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
            f"Merged MinerU pages are not continuous: expected 0..{source_page_count - 1}, got {page_indexes[:5]}...{page_indexes[-5:]}",
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
cd backend
uv run pytest tests/test_mineru_service.py::test_merge_segment_json_rewrites_page_indexes_and_asset_paths tests/test_mineru_service.py::test_merge_segment_json_rejects_page_count_mismatch -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/mineru_service.py backend/tests/test_mineru_service.py
git commit -m "feat: merge mineru page range segments"
```

---

### Task 4: Add Segmented Parse Orchestration

**Files:**
- Modify: `backend/tests/test_mineru_service.py`
- Modify: `backend/app/services/mineru_service.py`

- [ ] **Step 1: Write failing orchestration tests**

Append these tests to `backend/tests/test_mineru_service.py`:

```python
def test_parse_file_to_artifacts_uses_single_parse_for_pdf_at_200_pages(tmp_path, monkeypatch):
    from app.services import mineru_service

    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    calls = []

    monkeypatch.setattr(mineru_service, "_auth_token", lambda: "token")
    monkeypatch.setattr(mineru_service, "_pdf_page_count", lambda path: 200)

    def fake_parse_single(client, base_url, headers, source_path, output_dir, progress_callback=None, segment=None):
        calls.append(segment)
        json_path = output_dir / "parsed.json"
        json_path.write_text(json.dumps({"pdf_info": [{"page_idx": 0, "para_blocks": []}]}), encoding="utf-8")
        return mineru_service.MinerUParseArtifacts(json_path=json_path, batch_id="b1", task_id="t1")

    monkeypatch.setattr(mineru_service, "_parse_single_mineru_task", fake_parse_single)

    artifacts = mineru_service.parse_file_to_artifacts(str(source), tmp_path / "mineru")

    assert artifacts.json_path.name == "parsed.json"
    assert calls == [None]


def test_parse_file_to_artifacts_segments_pdf_over_200_pages(tmp_path, monkeypatch):
    from app.services import mineru_service

    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    seen_ranges = []

    monkeypatch.setattr(mineru_service, "_auth_token", lambda: "token")
    monkeypatch.setattr(mineru_service, "_pdf_page_count", lambda path: 278)

    def fake_parse_single(client, base_url, headers, source_path, output_dir, progress_callback=None, segment=None):
        assert segment is not None
        seen_ranges.append(segment.page_ranges)
        output_dir.mkdir(parents=True, exist_ok=True)
        pages = [{"page_idx": idx, "para_blocks": []} for idx in range(200 if segment.segment_index == 1 else 78)]
        json_path = output_dir / "parsed.json"
        json_path.write_text(json.dumps({"pdf_info": pages}), encoding="utf-8")
        markdown_path = output_dir / "full.md"
        markdown_path.write_text(f"segment {segment.segment_index}", encoding="utf-8")
        zip_path = output_dir / "mineru_result.zip"
        zip_path.write_bytes(b"zip")
        return mineru_service.MinerUParseArtifacts(
            json_path=json_path,
            markdown_path=markdown_path,
            zip_path=zip_path,
            batch_id=f"b{segment.segment_index}",
            task_id=f"t{segment.segment_index}",
        )

    monkeypatch.setattr(mineru_service, "_parse_single_mineru_task", fake_parse_single)

    artifacts = mineru_service.parse_file_to_artifacts(str(source), tmp_path / "mineru")

    assert seen_ranges == ["1-200", "201-400"]
    merged = json.loads(artifacts.json_path.read_text(encoding="utf-8"))
    assert len(merged["pdf_info"]) == 278
    assert merged["pdf_info"][200]["page_idx"] == 200
    assert (tmp_path / "mineru" / "segment_manifest.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd backend
uv run pytest tests/test_mineru_service.py::test_parse_file_to_artifacts_uses_single_parse_for_pdf_at_200_pages tests/test_mineru_service.py::test_parse_file_to_artifacts_segments_pdf_over_200_pages -q
```

Expected: FAIL because `_pdf_page_count` and `_parse_single_mineru_task` do not exist.

- [ ] **Step 3: Extract current single-task code**

In `backend/app/services/mineru_service.py`, add:

```python
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
        raise MinerUAPIError("MinerU result did not include full_zip_url", "MINERU_RESULT_INVALID")
    if progress_callback:
        progress_callback("downloading", {"batch_id": batch_id, "task_id": str(task.get("task_id") or ""), **_segment_progress(segment)})
    response = client.get(zip_url, headers=headers)
    _raise_for_status(response)

    artifacts = extract_zip_artifacts(response.content, output_dir)
    artifacts.batch_id = batch_id
    artifacts.task_id = str(task.get("task_id") or "")
    artifacts.zip_url = zip_url
    if artifacts.best_parse_path is None:
        raise MinerUAPIError("MinerU zip did not contain usable Markdown or structured JSON", "MINERU_RESULT_INVALID")
    return artifacts
```

Add:

```python
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
```

- [ ] **Step 4: Update wait polling to accept segment progress**

Change `_wait_batch_result` signature:

```python
def _wait_batch_result(
    client: httpx.Client,
    base_url: str,
    headers: dict[str, str],
    batch_id: str,
    progress_callback: Any | None = None,
    *,
    segment: MinerUSegment | None = None,
) -> dict[str, Any]:
```

When publishing polling progress, include segment data:

```python
progress_callback("polling", {"batch_id": batch_id, "task_id": str(task.get("task_id") or ""), **_segment_progress(segment)})
```

For done duration:

```python
progress_callback(
    "polling",
    {
        "batch_id": batch_id,
        "task_id": str(task.get("task_id") or ""),
        "mineru_poll_duration_ms": int((time.monotonic() - poll_started) * 1000),
        **_segment_progress(segment),
    },
)
```

- [ ] **Step 5: Add PDF page count helper**

Add:

```python
def _pdf_page_count(source: Path) -> int:
    try:
        import fitz

        with fitz.open(source) as doc:
            return int(doc.page_count)
    except Exception as exc:
        raise MinerUAPIError(f"Unable to read PDF page count: {source}", "MINERU_PDF_PAGE_COUNT_INVALID") from exc
```

- [ ] **Step 6: Route `parse_file_to_artifacts` through single or segmented path**

Replace the body after source validation in `parse_file_to_artifacts(...)` with this structure:

```python
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
```

Add segmented orchestrator:

```python
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
            if exc.error_code == "MINERU_TIMEOUT":
                raise MinerUAPIError(str(exc), "MINERU_SEGMENT_TIMEOUT", timeout=True) from exc
            raise MinerUAPIError(str(exc), "MINERU_SEGMENT_FAILED", timeout=exc.timeout) from exc
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
```

- [ ] **Step 7: Run orchestration tests**

Run:

```bash
cd backend
uv run pytest tests/test_mineru_service.py::test_parse_file_to_artifacts_uses_single_parse_for_pdf_at_200_pages tests/test_mineru_service.py::test_parse_file_to_artifacts_segments_pdf_over_200_pages -q
```

Expected: PASS.

- [ ] **Step 8: Run existing MinerU service tests**

Run:

```bash
cd backend
uv run pytest tests/test_mineru_service.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/app/services/mineru_service.py backend/tests/test_mineru_service.py
git commit -m "feat: segment long pdf mineru parsing"
```

---

### Task 5: Connect Segment Progress To Worker Without Changing Job Schema

**Files:**
- Modify: `backend/tests/test_document_parse_worker.py`
- Modify: `backend/app/services/document_parse_worker.py`

- [ ] **Step 1: Write failing worker progress test**

Append this test to `backend/tests/test_document_parse_worker.py`:

```python
@pytest.mark.asyncio
async def test_worker_records_segmented_mineru_progress_payload(tmp_path, monkeypatch):
    SessionLocal = _session_factory()
    db = SessionLocal()
    _, session, job = _make_contract_session_job(db, tmp_path, file_type="pdf")
    job_id = job.id
    db.close()

    monkeypatch.setattr(document_parse_worker.settings, "mineru_token", "test-token")
    events = []
    monkeypatch.setattr(document_parse_worker.sse_manager, "publish_nowait", lambda session_id, event, payload: events.append({"event": event, "payload": payload}))

    def fake_parse_file_to_artifacts(file_path, output_dir, progress_callback=None):
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "parsed.json"
        json_path.write_text(json.dumps({"pdf_info": [{"page_idx": 0, "para_blocks": []}]}), encoding="utf-8")
        manifest_path = output_dir / "segment_manifest.json"
        manifest_path.write_text(json.dumps({"segments": [{"segment_index": 2, "segment_count": 2, "page_ranges": "201-400"}]}), encoding="utf-8")
        if progress_callback:
            progress_callback("polling", {"batch_id": "b2", "task_id": "t2", "segment_index": 2, "segment_count": 2, "page_ranges": "201-400"})
        return document_parse_worker.mineru_service.MinerUParseArtifacts(json_path=json_path, batch_id="b2", task_id="t2")

    monkeypatch.setattr(document_parse_worker.mineru_service, "parse_file_to_artifacts", fake_parse_file_to_artifacts)

    await document_parse_worker.process_next_job(SessionLocal, worker_id="test-worker")

    db = SessionLocal()
    try:
        updated_job = db.query(DocumentParseJob).filter(DocumentParseJob.id == job_id).first()
        assert updated_job.status == "succeeded"
        assert updated_job.result_json_path.endswith("parsed.json")
        progress_payloads = [event["payload"] for event in events if event["event"] == "parse_progress"]
        assert any(payload.get("segment_index") == 2 and payload.get("segment_count") == 2 for payload in progress_payloads)
        timing = json.loads(updated_job.timing_json)
        metrics = timing["attempts"]["1"]["metrics"]
        assert metrics["mineru_total_duration_ms"] >= 0
    finally:
        db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd backend
uv run pytest tests/test_document_parse_worker.py::test_worker_records_segmented_mineru_progress_payload -q
```

Expected: FAIL because `_publish_progress_nowait` does not include segment payload fields.

- [ ] **Step 3: Preserve selected progress fields in timing metrics and SSE payload**

In `backend/app/services/document_parse_worker.py`, add:

```python
PROGRESS_PAYLOAD_KEYS = {
    "segment_index",
    "segment_count",
    "page_ranges",
    "page_start",
    "page_end_requested",
    "batch_id",
    "task_id",
}
```

Modify `_update_mineru_progress(...)` so selected non-duration values are stored as latest metrics:

```python
    for key, value in values.items():
        if key.endswith("_duration_ms") and isinstance(value, int | float):
            _record_timing_metric(job, key, int(value))
        elif key in PROGRESS_PAYLOAD_KEYS:
            _record_timing_metric(job, f"latest_{key}", value)
```

Because `_record_timing_metric` currently only accepts `int`, widen it:

```python
def _record_timing_metric(job: DocumentParseJob, key: str, value: Any) -> None:
    payload = _timing_payload(job)
    attempt = _attempt_timing(payload, job)
    attempt["metrics"][key] = value
    payload["updated_at"] = _iso(datetime.utcnow())
    _dump_timing_payload(job, payload)
```

Modify `_publish_progress_nowait(...)`:

```python
def _publish_progress_nowait(job: DocumentParseJob) -> None:
    timing = _public_timing_payload(job)
    metrics = timing.get("metrics") or {}
    progress_payload = {
        "session_id": job.session_id,
        "job_id": job.id,
        "provider": job.provider,
        "stage": job.stage,
        "retry_count": job.attempt_count,
        "max_retries": job.max_attempts,
        "timing": timing,
    }
    for key in PROGRESS_PAYLOAD_KEYS:
        value = metrics.get(f"latest_{key}")
        if value is not None:
            progress_payload[key] = value
    sse_manager.publish_nowait(job.session_id, "parse_progress", progress_payload)
```

- [ ] **Step 4: Run worker progress test**

Run:

```bash
cd backend
uv run pytest tests/test_document_parse_worker.py::test_worker_records_segmented_mineru_progress_payload -q
```

Expected: PASS.

- [ ] **Step 5: Run worker regression tests**

Run:

```bash
cd backend
uv run pytest tests/test_document_parse_worker.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/document_parse_worker.py backend/tests/test_document_parse_worker.py
git commit -m "feat: expose mineru segment parse progress"
```

---

### Task 6: End-To-End Regression Verification

**Files:**
- No new implementation files unless previous tasks reveal a regression.

- [ ] **Step 1: Run focused backend tests**

Run:

```bash
cd backend
uv run pytest tests/test_mineru_service.py tests/test_document_parse_worker.py tests/test_upload_mineru_json.py tests/test_water_review_mineru_json.py -q
```

Expected: PASS.

- [ ] **Step 2: Run compile check**

Run:

```bash
cd backend
python -m compileall app
```

Expected: all files compile with no syntax errors.

- [ ] **Step 3: Run frontend build only if frontend files changed**

Run only if implementation touched frontend:

```bash
cd frontend
npm run build
```

Expected: PASS.

- [ ] **Step 4: Optional live MinerU smoke test**

Use the already verified PDF path:

```text
/Users/liaoyp/Documents/project/水土-地拓知识库/水土知识库 2026/147浙江大学前沿学科综合大楼.pdf
```

Expected runtime behavior:

- Worker creates `mineru/segments/part-001/parsed.json`.
- Worker creates `mineru/segments/part-002/parsed.json`.
- Worker creates final `mineru/parsed.json`.
- Final JSON has `278` pages.
- Final `page_idx` is `0..277`.
- Session state becomes `parsed`, not `aborted`.
- Review/vector pipeline does not start until user clicks the review button.

- [ ] **Step 5: Inspect final diff scope**

Run:

```bash
git status --short
git diff --stat
```

Expected:

- Only planned files changed.
- Runtime DB `backend/contract_review.db` is not staged.
- Existing unrelated dirty files are not accidentally staged.

- [ ] **Step 6: Final commit**

If Task 6 required small regression fixes:

```bash
git add backend/app/services/mineru_service.py backend/app/services/document_parse_worker.py backend/tests/test_mineru_service.py backend/tests/test_document_parse_worker.py
git commit -m "test: verify mineru segmented parsing regressions"
```

If Task 6 made no code changes, do not create an empty commit.

---

## Self-Review

- Spec coverage:
  - PDF over 200 pages uses `page_ranges`: Task 1, Task 2, Task 4.
  - Multiple MinerU JSON files merge into one: Task 3, Task 4.
  - Continuous page indexes: Task 3.
  - Resource path preservation: Task 3.
  - No DB schema change: File Structure and Task 5.
  - Worker final artifact compatibility: Task 5 and Task 6.
  - Retry remains full job retry: no new retry state is introduced.
- Placeholder scan:
  - No placeholder markers or ambiguous catch-all steps.
- Type consistency:
  - `MinerUSegment`, `_plan_pdf_segments`, `_parse_single_mineru_task`, `_merge_segment_artifacts`, `_pdf_page_count`, and `_segment_progress` are introduced before use in later tasks.
