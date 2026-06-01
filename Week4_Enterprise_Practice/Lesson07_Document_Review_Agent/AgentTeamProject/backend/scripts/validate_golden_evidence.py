"""Validate a machine-readable golden evidence file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.golden_evidence_service import GoldenEvidenceError, load_golden_evidence_set


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate golden evidence annotations.")
    parser.add_argument("path", help="Path to golden evidence JSON.")
    args = parser.parse_args()

    try:
        summary = load_golden_evidence_set(args.path)
    except GoldenEvidenceError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(json.dumps(_summary_payload(summary), ensure_ascii=False, indent=2))
    return 0


def _summary_payload(summary: dict) -> dict:
    return {
        "version": summary["version"],
        "document_count": summary["document_count"],
        "check_item_count": summary["check_item_count"],
        "evidence_count": summary["evidence_count"],
    }


if __name__ == "__main__":
    raise SystemExit(main())
