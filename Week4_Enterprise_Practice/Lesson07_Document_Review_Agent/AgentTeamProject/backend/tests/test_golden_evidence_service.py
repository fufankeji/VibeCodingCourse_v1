import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.services.golden_evidence_service import GoldenEvidenceError, load_golden_evidence_set


def test_load_golden_evidence_set_summarizes_machine_readable_annotations(tmp_path):
    golden_path = tmp_path / "golden_evidence.json"
    golden_path.write_text(
        json.dumps(
            {
                "version": 1,
                "documents": [
                    {
                        "document_id": "doc-baiziwan-001",
                        "title": "朝阳区百子湾职工住宅项目",
                        "check_items": [
                            {
                                "check_item_id": "project_composition_consistency",
                                "evidence": [
                                    {
                                        "evidence_slot_id": "project_overview_content",
                                        "page": 12,
                                        "chunk_id": "chunk-project-overview",
                                        "block_id": "p12-b01",
                                        "expected_text": "建设内容包括住宅楼、配套用房和地下车库。",
                                    },
                                    {
                                        "evidence_slot_id": "approval_or_design_content",
                                        "page": 136,
                                        "chunk_id": "chunk-approval",
                                        "block_id": "p136-b02",
                                        "expected_text": "初步设计批复核定项目建筑面积。",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = load_golden_evidence_set(golden_path)

    assert result["document_count"] == 1
    assert result["check_item_count"] == 1
    assert result["evidence_count"] == 2
    assert result["documents"][0]["check_items"][0]["evidence"][0]["evidence_slot_id"] == "project_overview_content"


def test_load_golden_evidence_set_rejects_duplicate_slot_annotations(tmp_path):
    golden_path = tmp_path / "golden_evidence.json"
    golden_path.write_text(
        json.dumps(
            {
                "version": 1,
                "documents": [
                    {
                        "document_id": "doc-baiziwan-001",
                        "check_items": [
                            {
                                "check_item_id": "earthwork_balance",
                                "evidence": [
                                    {
                                        "evidence_slot_id": "earthwork_table",
                                        "page": 22,
                                        "chunk_id": "chunk-earthwork-a",
                                        "expected_text": "挖方10万m3。",
                                    },
                                    {
                                        "evidence_slot_id": "earthwork_table",
                                        "page": 23,
                                        "chunk_id": "chunk-earthwork-b",
                                        "expected_text": "填方8万m3。",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(GoldenEvidenceError, match="duplicate evidence_slot_id"):
        load_golden_evidence_set(golden_path)


def test_validate_golden_evidence_cli_outputs_summary(tmp_path):
    golden_path = tmp_path / "golden_evidence.json"
    golden_path.write_text(
        json.dumps(
            {
                "version": 1,
                "documents": [
                    {
                        "document_id": "doc-baiziwan-001",
                        "check_items": [
                            {
                                "check_item_id": "project_composition_consistency",
                                "evidence": [
                                    {
                                        "evidence_slot_id": "project_overview_content",
                                        "page": 12,
                                        "chunk_id": "chunk-project-overview",
                                        "expected_text": "建设内容包括住宅楼、配套用房和地下车库。",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [sys.executable, "scripts/validate_golden_evidence.py", str(golden_path)],
        cwd=".",
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["document_count"] == 1
    assert payload["check_item_count"] == 1
    assert payload["evidence_count"] == 1


def test_validate_golden_evidence_cli_rejects_invalid_file(tmp_path):
    golden_path = tmp_path / "golden_evidence.json"
    golden_path.write_text(json.dumps({"version": 1}), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, "scripts/validate_golden_evidence.py", str(golden_path)],
        cwd=".",
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 1
    assert "root.documents must be a non-empty list" in completed.stderr
    assert completed.stdout == ""


def test_example_golden_evidence_fixture_is_valid():
    fixture_path = Path("data/evaluation/golden_evidence.example.json")

    result = load_golden_evidence_set(fixture_path)

    assert result["document_count"] >= 1
    assert result["check_item_count"] >= 1
    assert result["evidence_count"] >= 1
