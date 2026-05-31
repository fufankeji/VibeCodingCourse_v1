# 水土保持方案智能审查上下文

本上下文记录审查对象解析、RAG 检索调试、证据定位和人工复核相关领域语言，避免后续 Module 命名漂移。

## Language

**Review Object**:
被审查的水土保持方案及其由 MinerU 或解析流程生成的结构化内容。
_Avoid_: contract, source file

**Review Session**:
一次围绕 Review Object 进行 AI 审查、人工复核和结果生成的工作会话。
_Avoid_: task, job

**Check Item**:
审查主题下可配置、可执行、可验收的一条检查要点；一个 Check Item 可以定义多个 Evidence Slot。
_Avoid_: ReviewItem, issue

**Artifact Readiness**:
Review Session 当前是否具备 parsed blocks、review chunks、vector index 和 RAG manifest 等可用产物的只读状态。
_Avoid_: parse status, file exists check

**Retrieval Debug**:
不创建正式审查结论的临时检索查询，用于验证 chunk、BM25、向量召回、邻近扩展和 rerank 质量。
_Avoid_: trial review, formal review

**Review Object Retrieval Debug**:
面向当前 Review Object 的临时检索验证，只判断项目文本块是否可被召回，不包含法规、规则库或外部知识库。
_Avoid_: regulation retrieval, knowledge base test

**Evidence Slot Retrieval**:
围绕一个审查规则需要核验的独立证据槽位分别召回项目文本块，再汇总给审查判断；一个规则可以包含多个证据槽位。
_Avoid_: single rule query, weighted keyword query

**Evidence Slot**:
审查规则中必须单独核验的一类证据需求，由配置显式维护，用于驱动 Evidence Slot Retrieval。
_Avoid_: inferred query, evidence scope text

**Missing Evidence**:
必填 Evidence Slot 没有召回到足够项目文本块时的审查状态；该状态下不能形成合格或不合格的最终技术判断。
_Avoid_: weak pass, guessed conclusion

**Evidence Slot Package**:
传给审查判断的结构化证据输入，按 Evidence Slot 分组包含少量原文 matches 和调试 trace；V1 不在进入审查判断前做 LLM 摘要。
_Avoid_: pre-summary, flat evidence list

**Parsed Attachment Evidence**:
Review Object 内已解析出的附件章节或材料块；V1 不把独立上传文件作为附件证据源。
_Avoid_: external attachment file, separate upload

**Formula Check**:
Check Item 下显式配置的工程量计算校验，由程序基于已抽取事实和单位归一化结果执行；LLM 不负责临时推导公式。
_Avoid_: natural language formula, LLM calculation

**Structured Earthwork Audit**:
围绕土石方和表土的结构化审查，抽取工程量、来源去向、调配说明和表土单独平衡证据，并执行 Formula Check。
_Avoid_: full engineering audit, cost audit

**MinerU Table Evidence**:
Review Object 中来自 MinerU table html 或表格截图的结构化表格证据；土石方表格优先使用该证据源，LangExtract 补充文字证据。
_Avoid_: OCR-only table, prose-only extraction

**Retrieval Enrichment Text**:
从 Review Object 原文、标题上下文和 MinerU 表格正文生成的连续文档文本，只用于 embedding 生成；不得混入页码、bbox、block type 等定位或结构标签。
_Avoid_: vector metadata, display text

**Atomic Block**:
Review Object 中由 MinerU 或 fallback parser 产生的最小可定位文档单元，保留原文、caption、page、bbox、page size、block id 和 parent section；Atomic Block 本身不是默认向量切片。
_Avoid_: vector chunk, review result

**Semantic Chunk**:
由同一章节路径下的一组 Atomic Block 组成的向量切片，embedding 只使用连续文档内容和表格可读文本，metadata 引用对应 Atomic Block。
_Avoid_: raw paragraph, page chunk

**Evidence Window**:
围绕命中 Semantic Chunk 扩展出的审查证据窗口，包含相邻 Atomic Block、章节标题、表格 caption/body 等上下文，用于规则判断和人工复核定位。
_Avoid_: neighbor-only retrieval, LLM summary

**Retrieval Location Metadata**:
用于定位和高亮 EvidenceAnchor 的页码、bbox、page size、MinerU block index 和 block id 等坐标元数据，不进入 embedding 语义文本。
_Avoid_: vector text, reasoning evidence

**EvidenceAnchor**:
指向 Review Object 中可定位证据位置的页码、block id、bbox 和坐标元数据。
_Avoid_: bbox, location

**Rule Preview**:
使用当前审查项草稿执行非持久化试审，以验证规则简报、召回证据和预期结论。
_Avoid_: debug query, saved rule

## Relationships

- A **Review Session** belongs to exactly one **Review Object**.
- A **Check Item** belongs to one review topic and can be executed through **Rule Preview** or formal review.
- **Artifact Readiness** describes whether a **Review Session** can run **Retrieval Debug** or **Rule Preview**.
- **Review Object Retrieval Debug** is scoped to parsed project text blocks inside one **Review Object**.
- One **Check Item** can define multiple **Evidence Slot** values.
- **Evidence Slot Retrieval** can produce multiple evidence matches for one **Evidence Slot**.
- A required **Evidence Slot** without sufficient matches creates **Missing Evidence**.
- **Evidence Slot Retrieval** produces an **Evidence Slot Package** for review judgment.
- **Parsed Attachment Evidence** is still part of the same **Review Object** in V1.
- **Structured Earthwork Audit** uses **MinerU Table Evidence** and LangExtract-grounded facts.
- **Formula Check** depends on extracted facts; missing or unsupported units create **Missing Evidence** instead of guessed values.
- **Retrieval Debug** and **Rule Preview** both produce evidence matches that carry **EvidenceAnchor** values.
- **EvidenceAnchor** points back to parsed blocks in the **Review Object**.
- **Retrieval Enrichment Text** improves vector recall without changing the user-visible chunk text.
- **Retrieval Location Metadata** supplies the coordinate fields used by **EvidenceAnchor**.
- **Semantic Chunk** references one or more **Atomic Block** values and carries an **Evidence Window** for review judgment.

## Example dialogue

> **Dev:** "If **Retrieval Debug** returns a chunk, should it create a ReviewItem?"
> **Domain expert:** "No. **Retrieval Debug** is non-persistent; only **Rule Preview** or formal review can lead to saved review outputs."

## Flagged ambiguities

- "合同" was used in older code and docs to mean **Review Object**; current domain language should use **Review Object** for 水土保持方案审查.
- "bbox" was used both as raw coordinate data and as source evidence location; use **EvidenceAnchor** when callers need a stable location interface.
- "知识检索测试" can mean Review Object retrieval or regulation knowledge retrieval; use **Review Object Retrieval Debug** when validating current project text blocks only.
- "向量数据" can mean **Retrieval Enrichment Text** or **Retrieval Location Metadata**; use the former for complete document semantics and the latter for click/highlight coordinates.
