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


def _mineru_doc_with_media() -> dict:
    return {
        "pdf_info": [
            {
                "page_idx": 0,
                "para_blocks": [
                    {
                        "bbox": [69, 550, 525, 698],
                        "type": "text",
                        "index": 2,
                        "lines": [
                            {
                                "spans": [
                                    {
                                        "bbox": [69, 550, 525, 698],
                                        "type": "table",
                                        "html": "<table><tr><td>项目组成</td><td>住宅楼</td></tr></table>",
                                        "image_path": "https://example.com/table.jpg",
                                    }
                                ]
                            }
                        ],
                    },
                    {
                        "bbox": [70, 100, 520, 420],
                        "type": "text",
                        "index": 3,
                        "lines": [
                            {
                                "spans": [
                                    {
                                        "bbox": [70, 100, 520, 420],
                                        "type": "image",
                                        "image_path": "https://example.com/figure.jpg",
                                    }
                                ]
                            }
                        ],
                    },
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


def test_parse_document_does_not_fallback_to_default_when_explicit_json_has_no_blocks(tmp_path, monkeypatch):
    default_md = tmp_path / "default.md"
    explicit_json = tmp_path / "empty-result.json"
    default_md.write_text("# 默认样例不应出现\n", encoding="utf-8")
    explicit_json.write_text(json.dumps({"pdf_info": [{"page_idx": 0, "para_blocks": []}]}), encoding="utf-8")
    monkeypatch.setattr(water_review_service, "DEFAULT_MINERU_JSON", tmp_path / "missing.json")
    monkeypatch.setattr(water_review_service, "DEFAULT_MINERU_MD", default_md)

    blocks = water_review_service.parse_document(str(explicit_json))

    assert blocks == []


def test_parse_document_preserves_mineru_table_html_and_image_paths(tmp_path):
    explicit_json = tmp_path / "mineru-media.json"
    explicit_json.write_text(json.dumps(_mineru_doc_with_media()), encoding="utf-8")

    blocks = water_review_service.parse_document(str(explicit_json))

    assert len(blocks) == 2
    table = blocks[0]
    assert table.type == "table"
    assert table.html == "<table><tr><td>项目组成</td><td>住宅楼</td></tr></table>"
    assert table.image_path == "https://example.com/table.jpg"
    assert "项目组成" in table.text
    image = blocks[1]
    assert image.type == "image"
    assert image.image_path == "https://example.com/figure.jpg"
    assert image.text == "https://example.com/figure.jpg"
