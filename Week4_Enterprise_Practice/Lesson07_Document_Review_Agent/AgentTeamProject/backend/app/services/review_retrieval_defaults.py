"""Shared retrieval defaults for review evidence slots."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EvidenceSlotRetrievalDefaults:
    candidate_top_k: int = 50
    vector_top_k: int = 50
    rrf_enabled: bool = True
    neighbor_expansion_enabled: bool = True
    rerank_candidate_top_n: int = 50
    final_top_k_per_slot: int = 5
    prompt_match_limit: int = 3
    min_matches: int = 1


EVIDENCE_SLOT_RETRIEVAL_DEFAULTS = EvidenceSlotRetrievalDefaults()


def evidence_slot_retrieval_defaults_trace() -> dict[str, int | bool]:
    defaults = asdict(EVIDENCE_SLOT_RETRIEVAL_DEFAULTS)
    applied_keys = {
        "candidate_top_k",
        "rerank_candidate_top_n",
        "final_top_k_per_slot",
        "prompt_match_limit",
        "min_matches",
    }
    return {key: value for key, value in defaults.items() if key in applied_keys}
