# MinerU PDF 分段解析与 JSON 合并设计

日期：2026-06-01

## 背景

MinerU 精准解析对单次解析任务有 200 页上限。当前系统上传 PDF 后，由 `DocumentParseJob` worker 调用 MinerU 解析，解析完成后保留 `parsed.json` / `full.md`，用户再手动启动数据清洗、向量化和审查。

已用真实文件验证：

- 文件：`/Users/liaoyp/Documents/project/水土-地拓知识库/水土知识库 2026/147浙江大学前沿学科综合大楼.pdf`
- 本地页数：278 页
- 请求：`files[0].page_ranges = "201-400"`
- MinerU 接受任务并完成解析
- 远端进度显示 `total_pages = 78`
- 结果包内 `origin.pdf` 为 78 页
- 结构化 JSON `pdf_info` 为 78 页
- 返回 JSON 的 `page_idx` 从 `0` 到 `77`

结论：超过 200 页的原 PDF 可以通过 `file.page_ranges` 分段解析同一份源文件；合并时必须重写分段 JSON 的页码。

## 目标

实现 PDF 超 200 页时的 MinerU 分段解析：

1. 200 页以内保持现有单次解析链路。
2. 200 页以上按每段最多 200 页生成 `page_ranges`。
3. 每段调用 MinerU，保存每段原始 zip、JSON、Markdown 和资源文件。
4. 合并多个 MinerU JSON 为一个最终 `parsed.json`。
5. 保证合并后的 `pdf_info[].page_idx` 全局连续。
6. 保留图片、表格等资源路径信息，不丢失原始 `image_path`。
7. 解析成功后只进入 `parsed`，不自动启动向量化和审查。

## 非目标

- 不实现物理拆 PDF 作为主路径。
- 不实现断点续传。
- 不新增 Celery/RQ。
- 不改 DOCX 和 MinerU JSON 上传链路。
- 不让 UI 暴露 MinerU 内部所有细碎 stage。
- 不在本次设计里重构整个 `DocumentParseJob` 状态机。

## 推荐方案

主路径使用 MinerU `file.page_ranges` 分段解析同一份 PDF。

对 278 页 PDF，生成：

```text
1-200
201-400
```

第二段实际只解析 201-278 页。MinerU 会返回 78 页结果，并把该段 JSON 的 `page_idx` 写成 `0..77`。系统合并时将第二段页码整体加上 `200`，变成 `200..277`。

## 架构影响

### `mineru_service`

新增 PDF 分段解析能力，保留现有单文件解析入口：

- `parse_file_to_artifacts(...)` 对外接口保持稳定。
- 内部判断文件类型和页数。
- PDF 页数 `<= 200` 时走现有单次解析。
- PDF 页数 `> 200` 时进入分段解析。
- DOCX 和 JSON 不进入分段逻辑。

新增内部职责：

- 读取 PDF 页数。
- 生成 `MinerUSegment` 列表。
- 对每个 segment 调用现有上传、轮询、下载、解压逻辑。
- 保存 segment manifest。
- 合并 segment JSON 和 Markdown。

### `document_parse_worker`

worker 仍只关心一个最终 `MinerUParseArtifacts`：

- `result_json_path` 指向合并后的 `parsed.json`。
- `result_markdown_path` 指向合并后的 `full.md`。
- `result_zip_path` 对分段任务不再表达单个 zip 的完整含义。

为避免扩表，分段细节写入 `segment_manifest.json`，由最终 JSON 所在目录可定位。若后续需要 UI 展示每段耗时，再考虑给 `DocumentParseJob` 增加 manifest 字段。

### UI

UI 只显示粗粒度状态：

- 等待解析
- MinerU 解析中
- 合并解析结果
- 解析完成
- 解析失败

超 200 页时，在 `MinerU 解析中` 下显示轻量进度：

```text
正在解析第 2/3 段：201-400 页
```

不展示 `upload_url_requested`、`uploaded`、`polling`、`downloading` 等内部状态。

## 数据结构

### Segment

```json
{
  "segment_index": 1,
  "segment_count": 2,
  "page_start": 201,
  "page_end_requested": 400,
  "page_offset": 200,
  "page_ranges": "201-400",
  "batch_id": "mineru batch id",
  "task_id": "mineru task id",
  "status": "succeeded",
  "page_count_returned": 78,
  "duration_seconds": 61,
  "zip_path": "segments/part-002/mineru_result.zip",
  "json_path": "segments/part-002/parsed.json",
  "markdown_path": "segments/part-002/full.md"
}
```

### Segment Manifest

```json
{
  "source_file_path": ".../source.pdf",
  "source_page_count": 278,
  "segment_size": 200,
  "segments": []
}
```

## 文件产物

分段 PDF 的 MinerU 产物目录：

```text
mineru/
  segments/
    part-001/
      mineru_result.zip
      parsed.json
      full.md
      images/
    part-002/
      mineru_result.zip
      parsed.json
      full.md
      images/
  parsed.json
  full.md
  segment_manifest.json
```

`parsed.json` 和 `full.md` 是系统后续数据清洗、向量化、审查使用的最终产物。

## JSON 合并规则

### 页码

每段返回 JSON 的 `pdf_info[].page_idx` 不能直接使用。合并规则：

```text
global_page_idx = segment.page_offset + local_page_order
```

其中 `local_page_order` 以该段 `pdf_info` 的数组顺序为准，而不是盲信 MinerU 返回的 `page_idx`。原因是 `page_ranges` 后返回的 `page_idx` 从 0 开始，且未来 MinerU 行为变化时，数组顺序比局部页码更适合作为分段内排序依据。

合并后必须校验：

- 最小 `page_idx` 为 0。
- 最大 `page_idx` 为 `source_page_count - 1`。
- 总页数等于本地 PDF 页数。
- 页码无重复。
- 页码无缺失。

失败时错误码为 `MINERU_MERGE_PAGE_MISMATCH`。

### 资源路径

不同 segment 可能都包含 `images/foo.jpg`，不能直接合并到同一目录。

合并时对资源路径做分段前缀：

```json
{
  "image_path": "segments/part-002/images/foo.jpg",
  "original_image_path": "images/foo.jpg"
}
```

规则：

- 所有已知图片路径字段都要重写为带 segment 前缀的路径。
- 原始路径保存到 `original_image_path`。
- 不删除未知字段。
- 不覆盖不同 segment 的同名资源。

如果发现合并后资源目标路径冲突，错误码为 `MINERU_ASSET_PATH_CONFLICT`。

### Markdown

`full.md` 按 segment 顺序拼接。

每段之间插入分隔注释，便于排查：

```markdown
<!-- MinerU segment 2/3 pages 201-400 -->
```

后续审查逻辑仍以 `parsed.json` 为主，Markdown 主要用于展示和诊断。

## 错误处理

### 单段失败

任意 segment 失败，整个 job 失败。已完成 segment 产物保留，便于排查。

错误码：

- `MINERU_SEGMENT_FAILED`：MinerU 返回 failed。
- `MINERU_SEGMENT_TIMEOUT`：该段轮询超时。
- `MINERU_SEGMENT_ZIP_MISSING`：该段没有 zip URL。
- `MINERU_SEGMENT_JSON_MISSING`：该段 zip 内没有可用结构化 JSON。

### 合并失败

合并失败不进入 `parsed`。

错误码：

- `MINERU_MERGE_PAGE_MISMATCH`
- `MINERU_ASSET_PATH_CONFLICT`
- `MINERU_MERGE_INVALID_JSON`

### Retry

retry 重新跑完整分段解析，不做断点续传。

理由：

- 断点续传需要持久化每段状态，当前 `DocumentParseJob` 表结构不适合。
- 解析任务属于低频长任务，v1 优先保证状态简单和结果一致。
- 已完成 segment 产物仅作为诊断材料，不作为 retry 输入。

## 性能与限流

v1 顺序执行每个 segment。

理由：

- 避免同时上传多个 25MB 以上 PDF 导致网络和 MinerU 限流问题。
- 避免多个远端任务并发轮询造成状态复杂化。
- 对 278 页 PDF，只增加一次远端任务，复杂度可控。

后续如果需要优化，可增加受控并发，例如最多 2 个 segment 并发，但不进入本次设计。

## 测试计划

### 单元测试

- 199 页生成单次解析。
- 200 页生成单次解析。
- 201 页生成两个 page_ranges：`1-200`、`201-400`。
- 278 页生成两个 page_ranges，并期望最终页数 278。
- 401 页生成三个 page_ranges：`1-200`、`201-400`、`401-600`。
- 第二段 JSON 返回 `page_idx 0..77` 时，合并后为 `200..277`。
- 合并后页码重复时报 `MINERU_MERGE_PAGE_MISMATCH`。
- 合并后页码缺失时报 `MINERU_MERGE_PAGE_MISMATCH`。
- 多段资源同名时路径带 `segments/part-xxx/` 前缀。
- `original_image_path` 被保留。
- Markdown 按 segment 顺序拼接。

### Worker 测试

- PDF 超 200 页时 worker 最终写入合并后的 `result_json_path`。
- 分段解析成功后 session 进入 `parsed`。
- 分段解析失败后 session 保持可 retry 的失败状态。
- retry 重跑完整 job，不复用旧 segment 成功状态。
- JSON 上传不进入分段逻辑。
- DOCX 上传不进入分段逻辑。

### 回归测试

- 现有 MinerU zip slip、大 zip、多 JSON 选择规则继续通过。
- 现有“解析完成后不自动启动向量化和审查”行为保持不变。
- 文档预览读取合并后的 `parsed.json`。
- 向量清洗与审查读取合并后的 `parsed.json`。

## 风险

### MinerU 行为变化

当前验证显示 `201-400` 会自动截断到真实尾页。如果 MinerU 未来改为越界报错，生成 page_ranges 时可以改为最后一段使用真实尾页，例如 `201-278`。本设计内部保存 `page_end_requested`，可支持调整。

### 资源路径字段不完整

MinerU JSON 可能在不同 block 类型里使用不同资源字段。实现时需要递归扫描常见字段，并保留未知字段。若遗漏字段，预览图片可能找不到，但文本审查不应受影响。

### 长文档耗时增加

顺序解析 600 页 PDF 至少需要 3 个远端任务。UI 必须显示 segment 进度，否则用户会误判为卡死。

### DB 可观测性不足

不扩表会导致分段 batch/task id 不方便直接查询。v1 用 `segment_manifest.json` 解决，后续如果运营需要按分段统计耗时，再扩展 DB。

## 验收标准

1. 278 页 PDF 能被自动分成两段提交 MinerU。
2. 最终合并 JSON 的 `pdf_info` 长度为 278。
3. 最终 `page_idx` 连续为 `0..277`。
4. 文档预览能展示合并后的解析结果。
5. 点击“开始向量清洗与数据审查”后使用合并 JSON，而不是任意单段 JSON。
6. 任意分段失败时，用户看到的是 MinerU 分段解析失败，而不是后处理失败或审查失败。
7. retry 后重新执行分段解析，最终可恢复。
