# Evidence slots and formula checks drive V1 review execution

V1 review execution uses explicit `evidence_slots` and `formula_checks` on each Check Item instead of deriving retrieval needs and formulas from free-form `review_criteria`. Retrieval first builds Evidence Slot Packages from Review Object text, MinerU table html and LangExtract-grounded facts; required missing slots or unsupported units create Missing Evidence rather than guessed conclusions.

Formula checks are executed by program code, not by the LLM. For the first two Check Items, V1 prioritizes project-composition consistency and Structured Earthwork Audit, supports common water-soil units (`万m³`, `万m3`, `万方`, `m³`, `m3`, `方`, `hm²`, `hm2`, `m²`, `m2`), parses MinerU table html before prose extraction, and covers earthwork total balance, topsoil standalone balance, borrow source, spoil destination, allocation explanation and missing-field judgment.
