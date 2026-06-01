def test_detect_file_type_rejects_legacy_word_by_extension():
    from app.services.upload_service import _detect_file_type

    assert _detect_file_type(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "方案.doc") is None


def test_detect_file_type_rejects_doc_extension_even_with_json_content():
    from app.services.upload_service import _detect_file_type

    assert _detect_file_type(b'{"pdf_info":[]}', "方案.doc") is None
