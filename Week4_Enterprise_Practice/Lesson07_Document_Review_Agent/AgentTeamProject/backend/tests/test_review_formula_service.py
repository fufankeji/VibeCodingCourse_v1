from app.services.review_formula_service import execute_formula_checks


def _fact(field_name: str, value: str, normalized_value: str, unit: str, fact_id: str):
    return {
        "fact_id": fact_id,
        "field_name": field_name,
        "value": value,
        "normalized_value": normalized_value,
        "unit": unit,
        "chunk_id": "chunk-1",
        "page_range": [1, 1],
        "source_text": f"{field_name}={value}",
        "confidence": 90,
    }


def test_formula_check_converts_m3_to_wan_m3():
    result = execute_formula_checks(
        [
            {
                "id": "earthwork_total_balance",
                "left_fields": ["excavation_volume", "borrow_volume"],
                "right_fields": ["fill_volume", "spoil_volume"],
                "tolerance": {"absolute": 0.0001, "unit": "万m3"},
            }
        ],
        [
            _fact("excavation_volume", "100000m3", "100000", "m3", "fact-excavation"),
            _fact("borrow_volume", "2万方", "2", "万方", "fact-borrow"),
            _fact("fill_volume", "80000m3", "80000", "m3", "fact-fill"),
            _fact("spoil_volume", "4万m³", "4", "万m³", "fact-spoil"),
        ],
    )

    check = result["checks"][0]
    assert check["status"] == "pass"
    assert check["left_value"] == 12.0
    assert check["right_value"] == 12.0
    assert check["field_values"]["excavation_volume"]["normalized_value"] == 10.0


def test_formula_check_reports_missing_required_fields():
    result = execute_formula_checks(
        [
            {
                "id": "earthwork_total_balance",
                "left_fields": ["excavation_volume", "borrow_volume"],
                "right_fields": ["fill_volume", "spoil_volume"],
                "tolerance": {"absolute": 0.01, "unit": "万m3"},
            }
        ],
        [
            _fact("excavation_volume", "10万m3", "10", "万m3", "fact-excavation"),
            _fact("fill_volume", "8万m3", "8", "万m3", "fact-fill"),
        ],
    )

    check = result["checks"][0]
    assert check["status"] == "missing"
    assert check["missing_fields"] == ["borrow_volume", "spoil_volume"]
    assert result["missing_count"] == 1


def test_formula_check_rejects_empty_or_duplicate_formula_fields():
    empty_result = execute_formula_checks(
        [{"id": "empty_formula", "left_fields": [], "right_fields": ["fill_volume"]}],
        [_fact("fill_volume", "8万m3", "8", "万m3", "fact-fill")],
    )
    duplicate_result = execute_formula_checks(
        [
            {
                "id": "duplicate_formula",
                "left_fields": ["excavation_volume", "excavation_volume"],
                "right_fields": ["fill_volume"],
            }
        ],
        [
            _fact("excavation_volume", "10万m3", "10", "万m3", "fact-excavation"),
            _fact("fill_volume", "20万m3", "20", "万m3", "fact-fill"),
        ],
    )

    assert empty_result["checks"][0]["status"] == "unsupported"
    assert "left_fields_empty" in empty_result["checks"][0]["config_errors"]
    assert duplicate_result["checks"][0]["status"] == "unsupported"
    assert "duplicate_fields" in duplicate_result["checks"][0]["config_errors"]


def test_formula_check_rejects_missing_or_unknown_units():
    result = execute_formula_checks(
        [
            {
                "id": "unknown_unit_formula",
                "left_fields": ["excavation_volume"],
                "right_fields": ["fill_volume"],
                "tolerance": {"absolute": 0.01, "unit": "万m3"},
            }
        ],
        [
            _fact("excavation_volume", "10", "10", "", "fact-excavation"),
            _fact("fill_volume", "10亩", "10", "亩", "fact-fill"),
        ],
    )

    check = result["checks"][0]
    assert check["status"] == "missing"
    assert check["missing_fields"] == ["excavation_volume", "fill_volume"]
    assert check["skipped_candidates"]["excavation_volume"][0]["reason"] == "missing_unit"
    assert check["skipped_candidates"]["fill_volume"][0]["reason"] == "unsupported_unit"


def test_formula_check_reports_skipped_high_confidence_candidate():
    result = execute_formula_checks(
        [
            {
                "id": "candidate_skip_formula",
                "left_fields": ["excavation_volume"],
                "right_fields": ["fill_volume"],
                "tolerance": {"absolute": 0.01, "unit": "万m3"},
            }
        ],
        [
            _fact("excavation_volume", "无法识别", "无法识别", "万m3", "fact-excavation-bad"),
            {**_fact("excavation_volume", "10万m3", "10", "万m3", "fact-excavation-good"), "confidence": 70},
            _fact("fill_volume", "10万m3", "10", "万m3", "fact-fill"),
        ],
    )

    check = result["checks"][0]
    assert check["status"] == "pass"
    assert check["field_values"]["excavation_volume"]["fact_id"] == "fact-excavation-good"
    assert check["skipped_candidates"]["excavation_volume"][0]["fact_id"] == "fact-excavation-bad"
    assert check["skipped_candidates"]["excavation_volume"][0]["reason"] == "invalid_numeric_value"
