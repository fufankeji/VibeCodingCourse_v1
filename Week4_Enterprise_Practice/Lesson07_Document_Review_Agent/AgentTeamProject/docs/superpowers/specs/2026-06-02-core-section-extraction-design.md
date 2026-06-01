# 核心章节定向抽取设计

日期：2026-06-02

## 背景

当前水土保持审查流水线会先解析文档、构建 `ReviewChunk`，再执行规则字段抽取、MinerU 表格事实抽取、可选 LangExtract 证据增强和 RAG 审查。现有字段抽取会拼接全量 chunks 后尝试抽取 `WATER_FIELDS` 中的所有字段；LangExtract 候选片段也主要依赖章节和关键词评分。

这会带来两个问题：

- 速度：全文候选片段越多，LangExtract 和后续事实整理成本越高。
- 质量：非目标章节中的同名词、泛化措施或背景描述可能污染字段结果。

本次目标是把关键信息抽取收敛到两个来源：`项目概况` 和 `土石方平衡`。系统先通过检索定位这两类核心片段，再只从核心片段中抽取核心字段。

## 目标

1. 抽取范围只覆盖项目概况和土石方平衡相关片段。
2. 核心字段采用 A 方案：
   - `project_name`
   - `construction_unit`
   - `construction_location`
   - `project_nature`
   - `land_area`
   - `disturbed_area`
   - `prevention_responsibility_area`
   - `excavation_volume`
   - `fill_volume`
   - `borrow_volume`
   - `spoil_volume`
   - `spoil_destination`
   - `borrow_area`
   - `comprehensive_utilization`
3. 先检索再抽取。检索负责缩小上下文，抽取负责生成字段和证据事实。
4. 保留 MinerU 表格事实优先级。土石方表格中的挖方、填方、借方、弃方仍应作为高置信事实进入结果。
5. 向量检索不可用时不阻塞主流程，降级到 BM25 和章节关键词过滤。

## 非目标

- 不扩展新的审查规则。
- 不重构前端页面或 API 输出结构。
- 不删除现有 `WATER_FIELDS` 常量，避免破坏前端和报告生成的字段协议。
- 不做全文知识图谱抽取。
- 不改变 MinerU 解析、chunk 构建、RAG 审查裁决的大流程。

## 推荐方案

采用“核心片段检索器 + 核心字段抽取器”的小范围后端改动。

### 核心片段检索

新增独立服务模块 `backend/app/services/core_extraction_service.py`，提供 `build_core_extraction_chunks(chunks, session_id, artifact_dir)`。

检索 query 固定为两组：

```text
项目概况 项目名称 建设单位 建设地点 建设性质 占地面积 防治责任范围 扰动面积
土石方平衡 挖方 填方 借方 弃方 余方 外运 消纳 综合利用 取土场 弃渣场
```

优先路径：

1. 在 `build_chunks(blocks)` 之后，为当前 session 提前准备 per-session Chroma 向量库。
2. 复用现有 `ChromaChunkStore` 和 `retrieve_for_query()`，开启 BM25 和邻近 chunk 扩展。
3. 合并两组 query 的命中结果，按 chunk id 去重。
4. 按原文顺序返回核心 chunks，避免打乱后续 source span 和章节判断。
5. 后续 `run_rag_review()` 继续使用同一 per-session 向量库路径；如实现阶段发现现有 `run_rag_review()` 仍会重建索引，应优先保持正确性，避免把索引复用扩大成本次必须完成的范围。

降级路径：

1. 如果向量构建失败、API key 不可用或检索异常，不抛出致命错误。
2. 使用 `retrieve_for_query(..., store=None, use_bm25=True)` 走 BM25。
3. 如果 BM25 仍无命中，使用章节和关键词过滤：
   - 章节包含 `项目概况`、`综合说明`、`工程概况`、`土石方`、`土石方平衡`
   - 正文包含核心字段关键词
4. 如果仍无命中，才退回原 chunks，保证流程不产生空结果。

### 核心字段抽取

调整 `extract_fields()` 的调用输入，而不是让它继续扫描全量 chunks。

核心字段集合固定为目标字段列表。`extract_fields(core_chunks)` 只主动填这些字段；输出仍按 `WATER_FIELDS` 补齐，非核心字段返回空值和低置信度，保持结构兼容。

项目概况字段使用确定性正则抽取：

- `project_name`
- `construction_unit`
- `construction_location`
- `project_nature`
- `land_area`
- `disturbed_area`
- `prevention_responsibility_area`

土石方字段使用确定性正则和表格事实共同抽取：

- `excavation_volume`
- `fill_volume`
- `borrow_volume`
- `spoil_volume`
- `spoil_destination`
- `borrow_area`
- `comprehensive_utilization`

如果同一字段同时来自 MinerU 表格事实和正文正则，表格事实优先进入 `langextract_facts`，后续 `facts_to_extracted_fields()` 可覆盖 fallback 字段。

### LangExtract 收敛

LangExtract 只接收核心 chunks。`PROMPT_DESCRIPTION` 中允许的 `extraction_class` 收敛到核心字段集合，不再要求模型关注防治措施、监测、投资估算、施工道路、表土链条等非本次目标字段。

这样做的结果是：

- 输入更短，响应更快。
- extraction class 更少，模型输出更稳定。
- 事实索引更聚焦，后续土石方审查更少受无关章节影响。

### 主流程接入

在 `run_pipeline()` 中，`build_chunks(blocks)` 之后新增核心片段选择：

```text
blocks -> chunks -> core_chunks -> fallback_fields
                         |
                         +-> LangExtract
                         +-> MinerU table facts
```

`chunks` 仍用于：

- 向量索引构建
- RAG 规则审查
- 前端证据定位

`core_chunks` 只用于：

- fallback 字段抽取
- LangExtract 候选输入

这样可以缩小抽取范围，同时不削弱后续审查检索的全文证据能力。

## 错误处理

- 向量库缺失：降级为 BM25。
- BM25 无命中：降级为章节和关键词过滤。
- 核心片段仍为空：退回全量 chunks，并在日志中记录 degraded 状态。
- LangExtract 失败：保持现有降级行为，使用 MinerU 表格事实和 fallback 字段继续。
- 外部 embedding 或 reranker 异常：不得导致解析和字段抽取失败。

## 缓存与产物

不改变现有 artifact 名称：

- `extracted_fields.json`
- `langextract_facts.json`
- `langextract_fact_index.json`
- `cross_chapter_findings.json`

新增一个调试产物：

- `core_extraction_chunks.json`

该文件记录核心 chunks 的来源 query、chunk id、section、page_range 和降级模式，用于解释为什么某些字段被抽取或漏抽。

## 测试计划

新增或更新后端单测：

1. `build_core_extraction_chunks` 能从包含多章节的 chunks 中只选出项目概况和土石方片段。
2. 当向量 store 缺失时，BM25/关键词降级仍能选中核心片段。
3. 非核心章节中的 `监测`、`防治措施`、`投资估算` 不会被主动填入核心抽取结果。
4. 土石方表格事实仍优先生成 `excavation_volume`、`fill_volume`、`borrow_volume`、`spoil_volume`。
5. `extract_fields(core_chunks)` 输出仍包含完整 `WATER_FIELDS` 顺序，兼容前端和报告。
6. LangExtract 的候选片段数量减少，并且允许字段不包含非目标字段。

目标验证命令：

```bash
cd backend
uv run pytest tests/test_langextract_service.py tests/test_earthwork_audit_service.py tests/test_rag_query_relevance.py
```

如新增专门测试文件，则同时运行该文件。

## 实施边界

预计只修改后端服务层和测试：

- `backend/app/services/water_review_service.py`
- `backend/app/services/water_review_extraction.py`
- `backend/app/services/langextract_service.py`
- `backend/app/services/core_extraction_service.py`
- 相关后端测试文件

不修改前端。

## 成功标准

1. 上传或解析完整文档后，字段抽取只从项目概况和土石方平衡相关片段生成核心字段。
2. `extracted_fields.json` 结构不变。
3. `langextract_facts.json` 中不再出现本次非目标字段的 LangExtract 事实。
4. 无向量库或外部检索失败时，主流程仍能完成。
5. 新增/更新的目标测试通过。
