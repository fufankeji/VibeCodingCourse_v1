# PRD: Evidence Slots 与 Formula Checks 驱动的 V1 审查执行

## Problem Statement

当前水土保持方案智能审查已经具备 Review Object 解析、RAG/BM25/向量召回、LangExtract 事实抽取和 Rule Preview 能力，但 Check Item 仍主要依赖自然语言 `review_criteria` 拼接成单一 query。对于长文档审查，这会导致关键证据召回不全面：一个检查要点往往需要同时读取项目概况、表格、附件章节和跨章节说明，单 query 容易只命中最显眼片段，漏掉判断所需的其他 Evidence Slot。

用户当前优先验证两个 Check Item：项目组成及建设内容一致性，以及土石方平衡（含表土）完整性。前者需要跨项目概要和 Parsed Attachment Evidence 判断一致性；后者需要从 MinerU Table Evidence 和 LangExtract-grounded facts 中抽取工程量、来源去向、调配说明并执行程序化 Formula Check。系统必须避免在必填证据缺失、单位不支持或公式字段不完整时让 LLM 猜测结论。

## Solution

V1 在 Check Item 配置中新增显式 `evidence_slots` 和 `formula_checks`。`evidence_slots` 用于把一个检查要点拆成可独立召回、可独立验收的 Evidence Slot；`formula_checks` 用于把土石方和表土计算公式从自然语言规则中取出，由程序执行单位归一化、公式计算和缺项判断。LLM 只接收 Evidence Slot Package 和 Formula Check 结果，用于解释审查结论，不负责临时推导公式或补全缺失数值。

Review Object Retrieval Debug、Rule Preview 和正式审查共用一套召回参数：BM25 candidate topK 50、vector candidate topK 50、RRF 融合、neighbor expansion、rerank candidate topN 50、final per slot topK 5、required slot minimum matches 1。给 LLM 的证据控制为每个 Evidence Slot 最多 3 条原文证据，其余 matches 保留为 trace。

V1 首批支持两个 Check Item：

1. 项目组成及建设内容应与立项文件或所处阶段的主体设计文件一致。
2. 土石方平衡（含表土）应明确挖方、填方、借方、弃方和调配情况；表土应单独平衡；借方来源、弃方去向应明确。

V1 只使用同一 Review Object 内已经解析出的附件章节或材料块作为 Parsed Attachment Evidence，不做多文件附件上传和独立附件解析。土石方表格优先解析 MinerU table html；如果只有 `image_path`，可作为定位证据，但不做图片 OCR 二次抽表。LangExtract 用于补充文字说明、来源去向、调配说明和表土措施。

## User Stories

1. As a rule author, I want to configure Evidence Slot values explicitly, so that each Check Item can define the evidence it needs instead of relying on one broad query.
2. As a rule author, I want each Evidence Slot to have its own queries, expected terms and preferred sections, so that retrieval can target the correct parts of a long Review Object.
3. As a rule author, I want required Evidence Slot values to be marked, so that missing critical evidence blocks final judgment.
4. As a rule author, I want optional Evidence Slot values to be allowed, so that supplementary context can improve judgment without causing false failure.
5. As a rule author, I want Check Item configuration to include Formula Check values, so that formulas are explicit and reviewable.
6. As a rule author, I want Formula Check expressions to reference extracted field names, so that formulas are stable across documents.
7. As a rule author, I want Formula Check tolerance to be configured, so that rounding and unit precision are handled consistently.
8. As a rule author, I want formula execution to be done by program code, so that LLMs do not invent calculations.
9. As a rule author, I want unsupported units to produce Missing Evidence, so that the system does not silently guess conversions.
10. As a reviewer, I want project-composition evidence from the project overview chapter, so that I can see the reported construction content.
11. As a reviewer, I want project-composition evidence from Parsed Attachment Evidence, so that I can compare it with approval or design-stage material.
12. As a reviewer, I want Missing Evidence when no parsed attachment chapter exists, so that the system does not infer consistency from only the project overview.
13. As a reviewer, I want the consistency result to show both sides of the comparison, so that I can audit why the system thinks content is consistent or inconsistent.
14. As a reviewer, I want earthwork volume evidence from text and tables, so that both narrative and tabular data are considered.
15. As a reviewer, I want MinerU Table Evidence to be parsed before prose extraction, so that table column relationships are not lost.
16. As a reviewer, I want LangExtract facts to remain grounded to source chunks, so that extracted values can be traced to original text.
17. As a reviewer, I want excavation volume to be extracted, so that earthwork total balance can be checked.
18. As a reviewer, I want fill volume to be extracted, so that earthwork total balance can be checked.
19. As a reviewer, I want borrow volume to be extracted, so that the need for borrow source evidence can be determined.
20. As a reviewer, I want spoil volume to be extracted, so that the need for spoil destination evidence can be determined.
21. As a reviewer, I want allocation or reuse explanation to be extracted, so that earthwork movement is not reduced to only totals.
22. As a reviewer, I want borrow source evidence to be extracted when borrow volume exists, so that the review can detect missing source explanation.
23. As a reviewer, I want spoil destination evidence to be extracted when spoil volume exists, so that the review can detect missing destination explanation.
24. As a reviewer, I want topsoil stripping evidence to be extracted, so that topsoil standalone balance can be checked.
25. As a reviewer, I want topsoil preservation evidence to be extracted, so that temporary storage and protection are visible.
26. As a reviewer, I want topsoil backfill or reuse evidence to be extracted, so that topsoil closed-loop use can be checked.
27. As a reviewer, I want topsoil to be evaluated separately from general earthwork, so that the system does not hide missing topsoil balance inside total earthwork.
28. As a reviewer, I want earthwork balance formula results, so that I can see whether `excavation + borrow` approximately equals `fill + spoil`.
29. As a reviewer, I want formula result status values, so that pass, fail, missing evidence and unsupported unit are distinguishable.
30. As a reviewer, I want each Formula Check to show the fields used, so that I can trace the result back to evidence.
31. As a reviewer, I want each field value to show unit normalization, so that I can identify conversion errors.
32. As a reviewer, I want each Evidence Slot Package to show matches used for prompt and trace-only matches, so that prompt context stays bounded but debugging remains possible.
33. As a reviewer, I want LLM explanations to cite Evidence Slot Package items, so that conclusions remain evidence-grounded.
34. As a reviewer, I want Missing Evidence to prevent final technical pass/fail judgment, so that incomplete retrieval does not become a false conclusion.
35. As a reviewer, I want the UI to show which Evidence Slot failed, so that I know what to fix in configuration or source material.
36. As a reviewer, I want the UI to show Formula Check failures separately from Missing Evidence, so that calculation problems and retrieval problems are not conflated.
37. As a reviewer, I want Review Object Retrieval Debug to use the same retrieval parameters as Rule Preview and formal review, so that debug results reflect production behavior.
38. As a reviewer, I want retrieval source badges to remain visible, so that BM25, vector, neighbor and rerank contributions are auditable.
39. As a reviewer, I want table evidence to be clickable back to parsed document blocks, so that tabular facts remain traceable.
40. As a reviewer, I want image-only table evidence to be shown as location evidence, so that unsupported extraction does not hide the source.
41. As a developer, I want a deep module for Evidence Slot retrieval, so that query fan-out, RRF fusion, rerank and Evidence Slot Package assembly are testable behind one interface.
42. As a developer, I want a deep module for Formula Check execution, so that unit normalization and tolerance comparison can be tested without invoking LLMs.
43. As a developer, I want a table extraction module for MinerU table html, so that table parsing can evolve independently from LangExtract.
44. As a developer, I want Check Item config normalization to preserve unknown future fields safely, so that adding `evidence_slots` and `formula_checks` does not break older configs.
45. As a developer, I want API contracts to expose Evidence Slot Package and Formula Check results, so that frontend does not parse internal RAG artifacts.
46. As a developer, I want formal review and Rule Preview to call the same evidence package builder, so that behavior does not drift.
47. As a developer, I want Retrieval Debug to be able to run by slot query, so that evidence recall can be diagnosed at slot level.
48. As a QA engineer, I want fixture-based tests for project-composition consistency, so that cross-section and Parsed Attachment Evidence behavior is stable.
49. As a QA engineer, I want fixture-based tests for earthwork table extraction, so that MinerU table html is parsed correctly.
50. As a QA engineer, I want formula tests for supported units, so that unit normalization remains deterministic.
51. As a QA engineer, I want tests for unsupported units, so that Missing Evidence behavior is explicit.
52. As a QA engineer, I want tests for missing required Evidence Slot values, so that LLM judgment is blocked when evidence is incomplete.
53. As a QA engineer, I want tests proving LLM prompts receive bounded per-slot evidence, so that prompt size does not grow unbounded.
54. As a product owner, I want V1 to support only two Check Item values first, so that the core retrieval and formula loop is validated before scaling rules.
55. As a product owner, I want future Check Item values to reuse the same Evidence Slot and Formula Check model, so that rule expansion is configuration-driven.

## Implementation Decisions

- Check Item configuration gains explicit `evidence_slots` and `formula_checks` fields.
- `evidence_slots` are maintained by configuration, not inferred from `review_criteria` in V1.
- `formula_checks` are maintained by configuration and executed by program code.
- LLMs do not derive formulas, do not perform authoritative arithmetic and do not fill missing numeric fields.
- Required Evidence Slot values with fewer than the configured minimum matches produce Missing Evidence.
- Missing Evidence prevents final pass/fail technical judgment for that Check Item.
- Review Object Retrieval Debug, Rule Preview and formal review share one retrieval parameter set.
- Shared retrieval defaults are BM25 candidate topK 50, vector candidate topK 50, RRF enabled, neighbor expansion enabled, rerank candidate topN 50, final per slot topK 5 and required slot minimum matches 1.
- LLM prompt input is an Evidence Slot Package, not a flat evidence list.
- Each Evidence Slot sends at most 3 original evidence matches to the LLM prompt; additional matches are trace-only.
- Evidence Slot Package contains slot id, label, status, matches used for prompt, trace matches and Missing Evidence reason when applicable.
- Formula Check result contains formula id, status, normalized operands, expected relation, tolerance, source fact references and failure reason.
- Structured Earthwork Audit uses MinerU Table Evidence before prose extraction.
- MinerU table html is parsed as structured table evidence.
- MinerU image-only table evidence is location evidence only in V1 and does not trigger image OCR extraction.
- LangExtract complements table extraction with source-grounded facts from prose.
- Supported volume units are `万m³`, `万m3`, `万方`, `m³`, `m3` and `方`.
- Supported area units are `hm²`, `hm2`, `m²` and `m2`.
- Unsupported units produce an unsupported-unit result and block formula judgment.
- Project-composition consistency uses current Review Object parsed content only.
- V1 uses Parsed Attachment Evidence inside the same Review Object and does not support independently uploaded attachment files.
- The first Check Item compares project overview construction content with Parsed Attachment Evidence from approval or design-stage material.
- The second Check Item performs Structured Earthwork Audit for total earthwork balance, topsoil standalone balance, borrow source, spoil destination, allocation explanation and missing-field judgment.
- A deep Evidence Slot Retrieval module should encapsulate slot query execution and package assembly behind a stable interface.
- A deep Formula Check module should encapsulate unit normalization, operand resolution and tolerance comparison behind a stable interface.
- A MinerU Table Evidence parser should encapsulate html table parsing and field candidate extraction.
- Existing LangExtract facts remain available as grounding and should be referenced rather than replaced.
- Existing retrieval match serialization should remain the public evidence-location boundary for UI click定位.
- API responses should expose slot and formula results directly rather than requiring frontend to inspect raw reasoning JSON.
- UI should show slot status, formula status, source matches, Missing Evidence and trace contribution labels.
- Existing `evidence_scope` remains useful as human-readable scope guidance; it is not the machine execution structure for V1.
- Existing `target_fields` can remain as display/precheck metadata; it is not a replacement for Evidence Slot definitions.

## Testing Decisions

- Good tests verify externally visible behavior: config input, API response, Rule Preview result, formal review output and UI-visible status.
- Tests should not assert private helper names or internal ranking implementation details beyond documented response contracts.
- Evidence Slot Retrieval tests should use fixture chunks and verify per-slot matches, Missing Evidence and bounded prompt matches.
- Retrieval tests should verify shared defaults are used consistently by Debug, Rule Preview and formal review.
- Formula Check tests should cover supported unit normalization for volume and area units.
- Formula Check tests should cover unsupported units and missing operands.
- Formula Check tests should cover tolerance behavior for earthwork total balance.
- Structured Earthwork Audit tests should cover excavation, fill, borrow, spoil, allocation explanation, borrow source and spoil destination.
- Topsoil tests should cover stripping, preservation, backfill/reuse and standalone missing evidence.
- MinerU Table Evidence tests should parse table html fixtures and preserve source anchors.
- Image-only table tests should verify location evidence is preserved but no OCR-derived values are invented.
- LangExtract integration tests should verify facts are included as grounded evidence and mapped into slot packages.
- Project-composition tests should cover matching overview and Parsed Attachment Evidence.
- Project-composition tests should cover missing Parsed Attachment Evidence causing Missing Evidence.
- Rule Preview tests should verify Missing Evidence prevents final pass/fail judgment.
- LLM prompt assembly tests should verify each slot sends at most 3 matches while retaining trace-only matches outside the prompt.
- Frontend tests should render Evidence Slot status, Formula Check status, Missing Evidence and clickable evidence matches.
- Existing retrieval debug and review configuration tests are prior art for API-level fixture setup.

## Out of Scope

- V1 does not implement independently uploaded attachment files.
- V1 does not implement multi-PDF attachment management.
- V1 does not perform image OCR for table screenshots.
- V1 does not perform full engineering design audit or cost audit.
- V1 does not perform分区级调配网络审计.
- V1 does not automatically infer Evidence Slot definitions from natural language review criteria.
- V1 does not automatically derive formula expressions from rule text.
- V1 does not support arbitrary unit conversion beyond the listed units.
- V1 does not resolve conflicting values across multiple document versions automatically.
- V1 does not replace formal human review for Missing Evidence cases.
- V1 does not implement PDF.js original-page overlay.
- V1 does not expand the first release beyond the two selected Check Item values.

## Further Notes

- This PRD follows the glossary in `CONTEXT.md` and ADR 0001.
- The most important implementation risk is confusing retrieval completeness with final judgment correctness. Missing Evidence must remain a first-class outcome.
- The second implementation risk is treating LangExtract as an audit engine. LangExtract is a grounded fact extraction layer; Formula Check and review execution must remain deterministic where possible.
- The third implementation risk is losing table structure by relying only on prose chunks. MinerU table html must be parsed before prose fallback for earthwork checks.
- The current `evidence_scope` content is too human-readable to drive machine execution and should not be overloaded further.
- The first implementation tracer bullet should be the earthwork total balance Formula Check using MinerU table html plus LangExtract-grounded fallback facts.
