import json

from app.services import water_review_service


def _mineru_doc(text: str) -> dict:
    return {
        "pdf_info": [
            {
                "page_idx": 0,
                "para_blocks": [
                    {
                        "bbox": [10, 20, 120, 40],
                        "type": "title",
                        "index": 1,
                        "lines": [
                            {
                                "spans": [
                                    {
                                        "content": text,
                                        "type": "text",
                                        "bbox": [10, 20, 120, 40],
                                    }
                                ]
                            }
                        ],
                    }
                ],
            }
        ]
    }


def test_parse_document_uses_explicit_mineru_json_before_default(tmp_path, monkeypatch):
    default_json = tmp_path / "default.json"
    explicit_json = tmp_path / "朝阳区百子湾职工住宅项目.json"
    default_json.write_text(json.dumps(_mineru_doc("北航默认样例")), encoding="utf-8")
    explicit_json.write_text(json.dumps(_mineru_doc("朝阳区百子湾职工住宅项目")), encoding="utf-8")
    monkeypatch.setattr(water_review_service, "DEFAULT_MINERU_JSON", default_json)
    monkeypatch.setattr(water_review_service, "DEFAULT_MINERU_MD", tmp_path / "missing.md")

    blocks = water_review_service.parse_document(str(explicit_json))

    assert [block.text for block in blocks] == ["朝阳区百子湾职工住宅项目"]
    assert blocks[0].page == 1
    assert blocks[0].bbox == [10.0, 20.0, 120.0, 40.0]
