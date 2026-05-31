from pathlib import Path


def test_prepare_parse_input_uses_mineru_json_for_pdf(tmp_path, monkeypatch):
    from app.services import upload_service
    from app.services.mineru_service import MinerUParseArtifacts

    source = tmp_path / "original.pdf"
    source.write_bytes(b"%PDF- fake")
    parsed_json = tmp_path / "mineru" / "parsed.json"
    parsed_json.parent.mkdir()
    parsed_json.write_text('{"pdf_info":[{"page_idx":0,"para_blocks":[]}]}', encoding="utf-8")

    calls = []

    def fake_parse(file_path: str, output_dir: Path) -> MinerUParseArtifacts:
        calls.append((file_path, output_dir))
        return MinerUParseArtifacts(json_path=parsed_json, markdown_path=None, zip_path=None)

    monkeypatch.setattr(upload_service.settings, "mineru_token", "test-token", raising=False)
    monkeypatch.setattr(upload_service.mineru_service, "parse_file_to_artifacts", fake_parse)
    monkeypatch.setattr(upload_service.ocr_service, "extract_text", lambda _: "local text")

    parse_path, text = upload_service._prepare_parse_input(str(source), "pdf")

    assert parse_path == str(parsed_json)
    assert text == ""
    assert calls == [(str(source), source.parent / "mineru")]


def test_prepare_parse_input_falls_back_to_local_text_without_mineru_token(tmp_path, monkeypatch):
    from app.services import upload_service

    source = tmp_path / "original.docx"
    source.write_bytes(b"PK\x03\x04 fake")

    monkeypatch.setattr(upload_service.settings, "mineru_token", "", raising=False)
    monkeypatch.setattr(upload_service.settings, "mineru_access_key", "", raising=False)
    monkeypatch.setattr(upload_service.ocr_service, "extract_text", lambda path: f"local:{path}")

    parse_path, text = upload_service._prepare_parse_input(str(source), "docx")

    assert parse_path == str(source)
    assert text == f"local:{source}"


def test_detect_file_type_accepts_legacy_word_by_extension():
    from app.services.upload_service import _detect_file_type

    assert _detect_file_type(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "方案.doc") == "doc"
