# 水土保持方案规则审查 MVP 开发记录

## 目标

快速验证“MinerU 解析数据 -> bbox-aware chunk -> Chroma/SiliconFlow RAG 召回 -> DeepSeek 规则裁决 -> 10 条 issue -> 人工复核页”的闭环。

## 当前范围

- 使用 `backend/data/MinerU_1 北京航空航天大学沙河校区图书馆项目水土保持方案.json` 作为解析数据源。
- 使用 `backend/data/水土保持方案审查规则集.json` 作为规则源，共 97 条规则。
- `backend/data/北京航空航天大学沙河校区图书馆项目-mineru.md` 仅作为 MinerU JSON 缺失时的文本兜底。
- 不接实时 OCR/Parser 服务；当前主路径使用 MinerU 已解析 JSON。
- 保留 PyMuPDF 作为缺少 MinerU JSON 时的文本 PDF fallback，并作为后续 RAG 文档接入候选。
- 复用现有 `ReviewItem`、LangGraph/HITL 流程和审核页。
- 新增 Chroma 本地持久化向量库，路径为 `backend/storage/vector_stores/water_review/{session_id}`。
- Embedding 使用 SiliconFlow，必须通过环境变量 `SILICONFLOW_API_KEY` 提供密钥。
- 规则裁决使用 DeepSeek structured JSON 输出，结果写回现有 `ReviewItem` 兼容字段。

## 已完成

- 新增水保专项 pipeline，支持 MinerU block -> bbox-aware chunk -> 字段抽取 -> RAG issue 生成。
- 新增 `rag_service`：
  - 写入 Chroma collection，并为每个向量文档保留 `chunk_id`、页码范围、section、bbox JSON、block ids。
  - 先做项目类型轻量判定，通用生产建设项目不会进入煤矿、铁路、公路、核电、管道等行业专项规则。
  - 每条规则按 `rule_name + category + target_fields + evidence_requirement + severity_policy` 构造 query。
  - 向量召回 top 12、BM25/关键词召回 top 12，RRF 融合后取 top 8，并做前后 chunk 邻接扩展。
  - 使用 `Qwen/Qwen3-Reranker-4B` 对融合与邻接扩展后的候选证据精排为 top 8。
  - DeepSeek 基于规则和召回证据输出结构化 issue。
- 规则审查输出收敛为 exactly 10 条高价值 issue，用于业务抽查。
- 每条 issue 带规则 ID、规则名称、风险等级、证据文本、页码、bbox 节点、实际情况、期望要求和修改建议。
- RAG 产物落盘：`rag_index_manifest.json`、`rag_retrievals.json`、`rag_issues.json`。
- 新增本地回灌脚本 `backend/scripts/backfill_water_rag_session.py`，用于在密钥配置完成后替换指定 session 的旧 issue。
- 当前演示 session `6f6410c8-e09d-439f-9ea8-fd73bd9e8049` 可回灌为 10 条水保 issue。
- 前端 HITL 右栏展示水保规则依据、证据节点数、bbox 数量和复核状态。
- 报告文案调整为水土保持方案审查意见稿风格。
- 已恢复 PyMuPDF 依赖与 `fitz` fallback；MinerU JSON 仍优先。
- RAG 失败时不再静默降级为关键词审查；会话进入 `aborted` 并写入 `system_failure` 审计日志。

## 环境变量

```bash
SILICONFLOW_API_KEY=...
SILICONFLOW_EMBEDDING_MODEL=Qwen/Qwen3-Embedding-4B
SILICONFLOW_EMBEDDING_DIMENSIONS=2560
SILICONFLOW_RERANKER_MODEL=Qwen/Qwen3-Reranker-4B
SILICONFLOW_RERANKER_INSTRUCTION=请根据水土保持方案审查规则查询，对候选证据片段进行相关性排序，优先保留能支撑规则判断、字段缺失或跨章节一致性核验的片段。
RAG_TOP_K=12
RAG_RERANK_TOP_N=8
RAG_MAX_ISSUES=10
```

DeepSeek 使用既有 `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` 配置；也可用 `REVIEW_LLM_API_KEY` / `REVIEW_LLM_BASE_URL` / `REVIEW_LLM_MODEL` 覆盖为 SiliconFlow 托管的 DeepSeek 系列模型。密钥只放环境或本地 `.env`，不写入代码。

## 验证命令

```bash
cd backend
uv run python -m py_compile app/services/rag_service.py app/services/water_review_service.py app/services/ocr_service.py app/services/hitl_service.py app/workflow/graph.py app/workflow/nodes.py app/services/report_service.py
uv run python - <<'PY'
from app.services.water_review_service import parse_document, build_chunks, load_rule_set
blocks = parse_document()
chunks = build_chunks(blocks)
rules = load_rule_set()
print(len(blocks), len(chunks), len(rules))
print(chunks[0].page_range, chunks[0].section, len(chunks[0].bbox_list))
PY
```

配置 `SILICONFLOW_API_KEY` 后执行真实 RAG：

```bash
cd backend
uv run python - <<'PY'
from app.services.water_review_service import run_pipeline
res = run_pipeline('ignored.pdf', 'storage/contracts/demo/water_review', 'demo-session')
print(len(res['rules']), len(res['review_items']))
print(res['rag']['index_manifest']['chunk_count'])
PY
```

回灌当前演示 session：

```bash
cd backend
uv run python scripts/backfill_water_rag_session.py 6f6410c8-e09d-439f-9ea8-fd73bd9e8049
```

```bash
curl -sS http://localhost:8001/health
curl -sS 'http://localhost:8001/api/v1/sessions/6f6410c8-e09d-439f-9ea8-fd73bd9e8049/items?limit=100'
```

```bash
cd frontend
npm run build
```

## 剩余风险

- 当前第一版只裁决排序靠前的规则直到产出 10 条 issue，后续可扩展为 97 条全量裁决和批处理缓存。
- bbox 已进入 issue 元数据并可展示数量，但还没有实现 PDF canvas 高亮回标。
- 演示 session 回灌会修改本地 SQLite 数据库；数据库和 storage 运行产物不应默认提交。
- PyMuPDF fallback 尚未接入 PyMuPDF4LLM / LangChain loader；后续可基于官方 RAG 路线扩展。
- 未配置 `SILICONFLOW_API_KEY` 时 RAG 会停止并报系统失败，这是预期行为，不做关键词静默降级。
