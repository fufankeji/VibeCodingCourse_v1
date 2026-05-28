from app.services.golden_evidence_evaluator import evaluate_golden_evidence_retrieval


def _golden_set(evidence):
    return {
        "document_count": 1,
        "check_item_count": 1,
        "evidence_count": len(evidence),
        "documents": [
            {
                "document_id": "doc-001",
                "check_items": [
                    {
                        "check_item_id": "earthwork_balance",
                        "evidence": evidence,
                    }
                ],
            }
        ],
    }


def test_evaluate_golden_evidence_retrieval_hits_by_chunk_id():
    golden_set = _golden_set(
        [
            {
                "evidence_slot_id": "earthwork_table",
                "chunk_id": "chunk-earthwork-table",
                "block_id": "",
                "page": 12,
                "expected_text": "土石方平衡表。",
            }
        ]
    )
    retrieval_results = {
        "documents": {
            "doc-001": {
                "check_items": {
                    "earthwork_balance": {
                        "slots": {
                            "earthwork_table": {
                                "matches": [
                                    {"chunk_id": "chunk-earthwork-table", "block_id": "other-block"}
                                ]
                            }
                        }
                    }
                }
            }
        }
    }

    result = evaluate_golden_evidence_retrieval(golden_set, retrieval_results)

    evidence_result = result["documents"][0]["check_items"][0]["evidence"][0]
    assert result["hit_count"] == 1
    assert result["miss_count"] == 0
    assert result["recall"] == 1.0
    assert evidence_result["status"] == "hit"
    assert evidence_result["matched_by"] == "chunk_id"


def test_evaluate_golden_evidence_retrieval_hits_by_block_id():
    golden_set = _golden_set(
        [
            {
                "evidence_slot_id": "topsoil_balance",
                "chunk_id": "",
                "block_id": "p78-b01",
                "page": 78,
                "expected_text": "表土剥离说明。",
            }
        ]
    )
    retrieval_results = {
        "documents": {
            "doc-001": {
                "check_items": {
                    "earthwork_balance": {
                        "slots": {
                            "topsoil_balance": {
                                "matches": [
                                    {"chunk_id": "other-chunk", "block_id": "p78-b01"}
                                ]
                            }
                        }
                    }
                }
            }
        }
    }

    result = evaluate_golden_evidence_retrieval(golden_set, retrieval_results)

    evidence_result = result["documents"][0]["check_items"][0]["evidence"][0]
    assert result["hit_count"] == 1
    assert evidence_result["status"] == "hit"
    assert evidence_result["matched_by"] == "block_id"


def test_evaluate_golden_evidence_retrieval_hits_serialized_block_ids_and_anchors():
    golden_set = _golden_set(
        [
            {
                "evidence_slot_id": "topsoil_balance",
                "chunk_id": "",
                "block_id": "p78-b01",
                "page": 78,
                "expected_text": "表土剥离说明。",
            },
            {
                "evidence_slot_id": "earthwork_text",
                "chunk_id": "",
                "block_id": "p76-b02",
                "page": 76,
                "expected_text": "土石方平衡文字说明。",
            },
        ]
    )
    retrieval_results = {
        "documents": {
            "doc-001": {
                "check_items": {
                    "earthwork_balance": {
                        "slots": {
                            "topsoil_balance": {
                                "matches": [{"chunk_id": "other", "block_ids": ["p78-b01"]}]
                            },
                            "earthwork_text": {
                                "matches": [
                                    {
                                        "chunk_id": "other",
                                        "anchors": [{"block_id": "p76-b02", "page": 76}],
                                    }
                                ]
                            },
                        }
                    }
                }
            }
        }
    }

    result = evaluate_golden_evidence_retrieval(golden_set, retrieval_results)

    evidence_results = result["documents"][0]["check_items"][0]["evidence"]
    assert result["hit_count"] == 2
    assert [evidence["matched_by"] for evidence in evidence_results] == ["block_id", "block_id"]


def test_evaluate_golden_evidence_retrieval_empty_results_marks_miss():
    golden_set = _golden_set(
        [
            {
                "evidence_slot_id": "earthwork_text",
                "chunk_id": "chunk-earthwork-summary",
                "block_id": "p76-b02",
                "page": 76,
                "expected_text": "土石方平衡文字说明。",
            }
        ]
    )

    result = evaluate_golden_evidence_retrieval(golden_set, {})

    evidence_result = result["documents"][0]["check_items"][0]["evidence"][0]
    assert result["document_count"] == 1
    assert result["check_item_count"] == 1
    assert result["evidence_count"] == 1
    assert result["hit_count"] == 0
    assert result["miss_count"] == 1
    assert result["recall"] == 0.0
    assert evidence_result["status"] == "miss"
    assert evidence_result["matched_by"] == "none"


def test_evaluate_golden_evidence_retrieval_malformed_results_are_misses():
    golden_set = _golden_set(
        [
            {
                "evidence_slot_id": "earthwork_text",
                "chunk_id": "chunk-earthwork-summary",
                "block_id": "p76-b02",
                "page": 76,
                "expected_text": "土石方平衡文字说明。",
            }
        ]
    )
    retrieval_results = {
        "documents": {
            "doc-001": {
                "check_items": {
                    "earthwork_balance": {
                        "slots": {"earthwork_text": {"matches": [{"chunk_id": "wrong"}, "bad-match"]}}
                    }
                }
            }
        }
    }

    result = evaluate_golden_evidence_retrieval(golden_set, retrieval_results)

    assert result["hit_count"] == 0
    assert result["miss_count"] == 1


def test_evaluate_golden_evidence_retrieval_malformed_layers_are_misses():
    golden_set = _golden_set(
        [
            {
                "evidence_slot_id": "earthwork_text",
                "chunk_id": "chunk-earthwork-summary",
                "block_id": "p76-b02",
                "page": 76,
                "expected_text": "土石方平衡文字说明。",
            }
        ]
    )

    for retrieval_results in (
        {"documents": []},
        {"documents": {"doc-001": []}},
        {"documents": {"doc-001": {"check_items": []}}},
        {"documents": {"doc-001": {"check_items": {"earthwork_balance": []}}}},
        {"documents": {"doc-001": {"check_items": {"earthwork_balance": {"slots": []}}}}},
        {"documents": {"doc-001": {"check_items": {"earthwork_balance": {"slots": {"earthwork_text": []}}}}}},
    ):
        result = evaluate_golden_evidence_retrieval(golden_set, retrieval_results)

        assert result["hit_count"] == 0
        assert result["miss_count"] == 1


def test_evaluate_golden_evidence_retrieval_non_list_matches_are_misses():
    golden_set = _golden_set(
        [
            {
                "evidence_slot_id": "earthwork_text",
                "chunk_id": "chunk-earthwork-summary",
                "block_id": "p76-b02",
                "page": 76,
                "expected_text": "土石方平衡文字说明。",
            }
        ]
    )
    retrieval_results = {
        "documents": {
            "doc-001": {
                "check_items": {
                    "earthwork_balance": {
                        "slots": {"earthwork_text": {"matches": {"chunk_id": "chunk-earthwork-summary"}}}
                    }
                }
            }
        }
    }

    result = evaluate_golden_evidence_retrieval(golden_set, retrieval_results)

    assert result["hit_count"] == 0
    assert result["miss_count"] == 1


def test_evaluate_golden_evidence_retrieval_calculates_partial_recall():
    golden_set = _golden_set(
        [
            {
                "evidence_slot_id": "earthwork_table",
                "chunk_id": "chunk-earthwork-table",
                "block_id": "p77-table-01",
                "page": 77,
                "expected_text": "土石方平衡表。",
            },
            {
                "evidence_slot_id": "topsoil_balance",
                "chunk_id": "chunk-topsoil-balance",
                "block_id": "p78-b01",
                "page": 78,
                "expected_text": "表土剥离说明。",
            },
        ]
    )
    retrieval_results = {
        "documents": {
            "doc-001": {
                "check_items": {
                    "earthwork_balance": {
                        "slots": {
                            "earthwork_table": {
                                "matches": [
                                    {"chunk_id": "chunk-earthwork-table", "block_id": "other-block"}
                                ]
                            },
                            "topsoil_balance": {
                                "matches": [
                                    {"chunk_id": "other-chunk", "block_id": "other-block"}
                                ]
                            },
                        }
                    }
                }
            }
        }
    }

    result = evaluate_golden_evidence_retrieval(golden_set, retrieval_results)

    evidence_results = result["documents"][0]["check_items"][0]["evidence"]
    assert result["evidence_count"] == 2
    assert result["hit_count"] == 1
    assert result["miss_count"] == 1
    assert result["recall"] == 0.5
    assert [evidence["status"] for evidence in evidence_results] == ["hit", "miss"]
