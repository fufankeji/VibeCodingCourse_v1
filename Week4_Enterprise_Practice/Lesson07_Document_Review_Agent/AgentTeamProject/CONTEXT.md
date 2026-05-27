# 水土保持方案智能审查上下文

本上下文记录审查对象解析、RAG 检索调试、证据定位和人工复核相关领域语言，避免后续 Module 命名漂移。

## Language

**Review Object**:
被审查的水土保持方案及其由 MinerU 或解析流程生成的结构化内容。
_Avoid_: contract, source file

**Review Session**:
一次围绕 Review Object 进行 AI 审查、人工复核和结果生成的工作会话。
_Avoid_: task, job

**Artifact Readiness**:
Review Session 当前是否具备 parsed blocks、review chunks、vector index 和 RAG manifest 等可用产物的只读状态。
_Avoid_: parse status, file exists check

**Retrieval Debug**:
不创建正式审查结论的临时检索查询，用于验证 chunk、BM25、向量召回、邻近扩展和 rerank 质量。
_Avoid_: trial review, formal review

**EvidenceAnchor**:
指向 Review Object 中可定位证据位置的页码、block id、bbox 和坐标元数据。
_Avoid_: bbox, location

**Rule Preview**:
使用当前审查项草稿执行非持久化试审，以验证规则简报、召回证据和预期结论。
_Avoid_: debug query, saved rule

## Relationships

- A **Review Session** belongs to exactly one **Review Object**.
- **Artifact Readiness** describes whether a **Review Session** can run **Retrieval Debug** or **Rule Preview**.
- **Retrieval Debug** and **Rule Preview** both produce evidence matches that carry **EvidenceAnchor** values.
- **EvidenceAnchor** points back to parsed blocks in the **Review Object**.

## Example dialogue

> **Dev:** "If **Retrieval Debug** returns a chunk, should it create a ReviewItem?"
> **Domain expert:** "No. **Retrieval Debug** is non-persistent; only **Rule Preview** or formal review can lead to saved review outputs."

## Flagged ambiguities

- "合同" was used in older code and docs to mean **Review Object**; current domain language should use **Review Object** for 水土保持方案审查.
- "bbox" was used both as raw coordinate data and as source evidence location; use **EvidenceAnchor** when callers need a stable location interface.
