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
