from app.services.earthwork_audit_service import execute_earthwork_audit


def _field(field_name: str, value: str, normalized_value: str = "", unit: str = "") -> dict:
    return {
        "field_name": field_name,
        "value": value,
        "normalized_value": normalized_value or value,
        "unit": unit,
        "fact_id": f"fact-{field_name}",
        "chunk_id": "chunk-earthwork",
        "page_range": [22, 22],
        "source_text": f"{field_name}={value}",
        "confidence": 90,
    }


def test_earthwork_audit_requires_source_destination_and_allocation_when_volumes_exist():
    result = execute_earthwork_audit(
        [
            _field("excavation_volume", "10.00万m3", "10.00", "万m3"),
            _field("fill_volume", "8.00万m3", "8.00", "万m3"),
            _field("borrow_volume", "2.00万m3", "2.00", "万m3"),
            _field("spoil_volume", "4.00万m3", "4.00", "万m3"),
        ]
    )

    assert result["status"] == "needs_evidence"
    missing_ids = [check["audit_check_id"] for check in result["checks"] if check["status"] == "missing"]
    assert "borrow_source" in missing_ids
    assert "spoil_destination" in missing_ids
    assert "allocation_explanation" in missing_ids


def test_earthwork_audit_reports_topsoil_chain_separately_from_total_balance():
    result = execute_earthwork_audit(
        [
            _field("land_area", "1.2hm2", "1.2", "hm2"),
            _field("topsoil_stripping", "表土剥离"),
        ]
    )

    topsoil = next(check for check in result["checks"] if check["audit_check_id"] == "topsoil_standalone_chain")
    assert topsoil["status"] == "missing"
    assert topsoil["missing_fields"] == ["topsoil_preservation", "topsoil_backfill"]
