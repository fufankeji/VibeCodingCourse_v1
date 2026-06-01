import io
import json
import zipfile

import httpx


def _mineru_zip_bytes() -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as zf:
        zf.writestr(
            "result/demo_middle.json",
            json.dumps(
                {
                    "pdf_info": [
                        {
                            "page_idx": 0,
                            "para_blocks": [
                                {
                                    "type": "title",
                                    "index": 1,
                                    "bbox": [1, 2, 3, 4],
                                    "lines": [{"spans": [{"content": "水土保持方案"}]}],
                                }
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        )
        zf.writestr("result/full.md", "# 水土保持方案\n")
        zf.writestr("result/demo_content_list.json", json.dumps([{"text": "fallback"}]))
    return payload.getvalue()


def test_extract_zip_artifacts_picks_structured_mineru_json(tmp_path):
    from app.services.mineru_service import extract_zip_artifacts

    result = extract_zip_artifacts(_mineru_zip_bytes(), tmp_path)

    assert result.json_path is not None
    assert result.markdown_path is not None
    assert result.best_parse_path == result.json_path
    assert json.loads(result.json_path.read_text(encoding="utf-8"))["pdf_info"][0]["page_idx"] == 0
    assert result.markdown_path.read_text(encoding="utf-8").startswith("# 水土保持方案")


def test_extract_zip_artifacts_rejects_zip_slip(tmp_path):
    from app.services.mineru_service import MinerUAPIError, extract_zip_artifacts

    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as zf:
        zf.writestr("../escape.json", "{}")

    try:
        extract_zip_artifacts(payload.getvalue(), tmp_path)
    except MinerUAPIError as exc:
        assert exc.error_code == "MINERU_ZIP_UNSAFE"
    else:
        raise AssertionError("unsafe zip member should fail")


def test_extract_zip_artifacts_selects_largest_structured_json(tmp_path):
    from app.services.mineru_service import extract_zip_artifacts

    small = {"pdf_info": [{"page_idx": 0, "para_blocks": [{"type": "text"}]}]}
    large = {
        "pdf_info": [
            {"page_idx": 0, "para_blocks": [{"type": "text"}, {"type": "title"}]},
            {"page_idx": 1, "para_blocks": [{"type": "table"}]},
        ]
    }
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as zf:
        zf.writestr("small.json", json.dumps(small))
        zf.writestr("large.json", json.dumps(large))

    result = extract_zip_artifacts(payload.getvalue(), tmp_path)

    assert result.json_path is not None
    assert len(json.loads(result.json_path.read_text(encoding="utf-8"))["pdf_info"]) == 2


def test_extract_zip_artifacts_rejects_invalid_zip(tmp_path):
    from app.services.mineru_service import MinerUAPIError, extract_zip_artifacts

    try:
        extract_zip_artifacts(b"not a zip", tmp_path)
    except MinerUAPIError as exc:
        assert exc.error_code == "MINERU_RESULT_INVALID"
    else:
        raise AssertionError("invalid zip should fail")


def test_raise_for_status_maps_mineru_http_errors():
    from app.services.mineru_service import MinerUAPIError, _raise_for_status

    request = httpx.Request("GET", "https://mineru.example/test")
    cases = [
        (401, "MINERU_AUTH_FAILED"),
        (403, "MINERU_AUTH_FAILED"),
        (429, "MINERU_RATE_LIMITED"),
        (500, "MINERU_REMOTE_FAILED"),
    ]

    for status_code, expected_code in cases:
        response = httpx.Response(status_code, request=request)
        try:
            _raise_for_status(response)
        except MinerUAPIError as exc:
            assert exc.error_code == expected_code
        else:
            raise AssertionError(f"{status_code} should fail")


def test_auth_token_requires_mineru_token_only(monkeypatch):
    from app.services import mineru_service

    monkeypatch.setattr(mineru_service.settings, "mineru_token", "", raising=False)

    assert mineru_service._auth_token() == ""


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

    batch_id = _submit_local_file(
        client,
        "https://mineru.example/api/v4",
        {"Authorization": "Bearer test"},
        source,
        segment=segment,
    )

    assert batch_id == "batch-201-400"
    assert uploaded["called"] is True
    assert captured_payload["files"][0]["page_ranges"] == "201-400"


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
    part1_pages = [{"page_idx": idx, "para_blocks": []} for idx in range(200)]
    part1_pages[0]["para_blocks"] = [{"type": "image", "image_path": "images/a.jpg"}]
    part2_pages = [
        {"page_idx": 0, "para_blocks": [{"type": "image", "image_path": "images/a.jpg"}]},
        {"page_idx": 1, "para_blocks": [{"type": "text", "lines": [{"spans": [{"content": "尾页"}]}]}]},
    ]
    (part1 / "parsed.json").write_text(json.dumps({"pdf_info": part1_pages}), encoding="utf-8")
    (part2 / "parsed.json").write_text(json.dumps({"pdf_info": part2_pages}), encoding="utf-8")
    (part1 / "full.md").write_text("第一页\n", encoding="utf-8")
    (part2 / "full.md").write_text("尾页\n", encoding="utf-8")

    artifacts = _merge_segment_artifacts(
        source_file_path="/tmp/source.pdf",
        source_page_count=202,
        output_dir=tmp_path,
        segments=segments,
        segment_results=[
            {
                "segment": segments[0],
                "json_path": part1 / "parsed.json",
                "markdown_path": part1 / "full.md",
                "zip_path": part1 / "mineru_result.zip",
                "batch_id": "b1",
                "task_id": "t1",
                "duration_ms": 10,
            },
            {
                "segment": segments[1],
                "json_path": part2 / "parsed.json",
                "markdown_path": part2 / "full.md",
                "zip_path": part2 / "mineru_result.zip",
                "batch_id": "b2",
                "task_id": "t2",
                "duration_ms": 20,
            },
        ],
    )

    assert artifacts.json_path is not None
    assert artifacts.markdown_path is not None
    merged = json.loads(artifacts.json_path.read_text(encoding="utf-8"))
    assert [page["page_idx"] for page in merged["pdf_info"]] == list(range(202))
    first_block = merged["pdf_info"][0]["para_blocks"][0]
    segment_two_block = merged["pdf_info"][200]["para_blocks"][0]
    assert first_block["image_path"] == "segments/part-001/images/a.jpg"
    assert first_block["original_image_path"] == "images/a.jpg"
    assert segment_two_block["image_path"] == "segments/part-002/images/a.jpg"
    assert segment_two_block["original_image_path"] == "images/a.jpg"
    markdown = artifacts.markdown_path.read_text(encoding="utf-8")
    assert "MinerU segment 1/2 pages 1-200" in markdown
    assert "MinerU segment 2/2 pages 201-400" in markdown
    manifest = json.loads((tmp_path / "segment_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_page_count"] == 202
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
                {
                    "segment": segment,
                    "json_path": part / "parsed.json",
                    "markdown_path": None,
                    "zip_path": None,
                    "batch_id": "b1",
                    "task_id": "t1",
                    "duration_ms": 10,
                }
            ],
        )
    except MinerUAPIError as exc:
        assert exc.error_code == "MINERU_MERGE_PAGE_MISMATCH"
    else:
        raise AssertionError("page count mismatch should fail")
