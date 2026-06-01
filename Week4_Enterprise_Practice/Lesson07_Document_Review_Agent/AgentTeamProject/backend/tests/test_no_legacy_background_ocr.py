from pathlib import Path


def test_legacy_background_ocr_entrypoint_is_removed():
    root = Path(__file__).resolve().parents[1] / "app"
    haystack = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.py"))

    assert "_background_ocr" not in haystack
    assert "create_task(_background_ocr" not in haystack
