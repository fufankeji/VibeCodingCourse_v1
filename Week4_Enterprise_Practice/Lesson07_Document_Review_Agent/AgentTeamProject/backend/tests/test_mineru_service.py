import io
import json
import zipfile


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
