# 统一文档审查工作台设计

## 背景

当前系统已经有一个接近目标形态的 `HITLReviewPage`：三栏工作台、左侧文档导航、中间文档/证据区、右侧规则审查与人工复核区。问题是解析完成页、字段确认页、AI 扫描页和人工复核页仍然分散在多套页面里，导致用户无法判断自己看到的是原始 PDF、MinerU 解析结果、字段产物、向量缓存还是规则审查项。

本设计将现有 HITL 页面抽象为统一的文档审查工作台。不同阶段进入同一个工作台壳，右侧阶段面板随当前流程变化。

## 目标

1. `查看解析文档` 必须进入真实文档工作台，而不是孤立的解析块列表页。
2. 原始 PDF、MinerU 解析证据、抽取字段、向量/规则审查状态和人工复核项必须出现在同一个上下文中。
3. 已解析过的 PDF 不得因为查看或进入下一步而重新上传或重新解析。
4. `aborted`、`parsed`、`scanning`、`hitl_*` 状态都允许查看已生成的数据；状态只控制动作权限，不控制查看权限。
5. 不伪装 PDF 精准高亮。当前阶段只承诺原始 PDF 浏览、解析证据高亮、证据跳页和 bbox 信息展示。

## 非目标

1. 不实现 PDF canvas bbox overlay。
2. 不实现 PDF.js/react-pdf 坐标投影。
3. 不实现报告 PDF 回链。
4. 不重写 MinerU 解析 worker。
5. 不把 LangExtract 重新放回主审查链路。

## 方案选择

采用“一个工作台，多种阶段面板”的架构。

不选择继续维护独立 `ParsedDocumentPage`，因为它会制造第二套文档查看逻辑。也不选择只在规则审查后复用 HITL 页面，因为解析、字段和扫描阶段仍会割裂。

## 路由

保留现有 URL，不破坏入口：

- `/contracts/:id/document`
- `/contracts/:id/fields`
- `/contracts/:id/scanning`
- `/contracts/:id/review`

这些路由最终都渲染同一个工作台容器。工作台根据路径推导 `mode`：

- `document`: 查看原始 PDF 与 MinerU 解析证据
- `fields`: 查看和确认关键信息
- `scanning`: 查看数据清洗、向量索引、RAG 检索和规则判定状态
- `review`: 查看规则审查项并执行人工复核

旧页面可以先保留为 thin wrapper，只负责把路由参数传给统一工作台。等功能稳定后再删除重复页面代码。

## 信息架构

工作台固定三栏：

### 左栏：文档导航与流程状态

职责：

- 展示页码列表和大纲。
- 展示当前流程阶段。
- 展示解析页数、解析块数、审查项数量、缓存状态。
- 支持点击页码切换中栏文档页。

左栏不承载业务动作，避免和右栏阶段动作混杂。

### 中栏：文档视图

职责：

- 默认展示原始 PDF。
- 支持切换到 MinerU 解析证据视图。
- 支持上一页、下一页、跳转证据页。
- 解析证据视图展示文本、表格、图片、chunk、bbox、block_id。

原始 PDF 通过后端 `source_pdf_url` 读取，不从前端拼接本地路径。JSON 上传或 DOCX 转换场景没有原始 PDF 时，自动进入解析证据视图。

### 右栏：阶段面板

右栏根据 `mode` 切换：

- `document`: 解析摘要、开始清洗与向量审查、查看已生成产物。
- `fields`: 关键信息列表、来源页码、置信度、确认状态。
- `scanning`: pipeline 阶段、缓存命中、失败原因、重新启动按钮。
- `review`: 审查项列表、规则依据、证据节点、人工复核动作。

右栏是唯一承载阶段动作的区域。

## 组件边界

从 `HITLReviewPage` 拆出可复用组件：

- `ReviewWorkspacePage`
  - 读取 `sessionId` 和 `mode`。
  - 协调数据加载。
  - 不渲染具体 UI 细节。

- `ReviewWorkspaceShell`
  - 三栏布局。
  - 接收左栏、中栏、右栏 slot。

- `DocumentNavigator`
  - 页码、大纲、流程阶段和轻量统计。

- `DocumentViewer`
  - 原始 PDF / 解析证据切换。
  - 负责页码跳转和 evidence anchor 跳转。

- `ParsedEvidenceView`
  - 从现有 `DocumentPageView`、`DocumentBlockView` 拆出。
  - 只渲染 MinerU 解析块。

- `WorkspaceStagePanel`
  - 根据 `mode` 选择阶段面板。

- `ReviewIssuePanel`
  - 从现有 HITL 右栏拆出。
  - 只处理审查项、证据、决策、撤销、规则配置预览。

- `PipelineStatusPanel`
  - 从解析页的状态展示逻辑中抽出。
  - 只展示真实后端 pipeline 状态。

- `ExtractedFieldsSummary`
  - 保留现有组件。
  - 在 `fields`、`scanning`、`review` 阶段复用。

## 数据加载

工作台统一加载以下数据，但按 mode 分级阻塞：

- `GET /sessions/:id`
- `GET /sessions/:id/document-content`
- `GET /sessions/:id/review-pipeline-status`
- `GET /sessions/:id/langextract-facts`
- `GET /sessions/:id/items`
- `GET /sessions/:id/rule-topics`

阻塞规则：

- `document`: session + document-content 必须成功；其他数据后台加载。
- `fields`: session + document-content + fields 必须成功。
- `scanning`: session + pipeline-status 必须成功；items 后台轮询。
- `review`: session + document-content + items 必须成功。

接口失败时，只影响对应面板，不让整个工作台白屏。

## 状态规则

查看权限：

- 只要有 `document-content` 或 `source_pdf_url`，就允许进入工作台查看。
- `aborted` 仍可查看原始 PDF、解析证据、字段和已生成审查项。
- `aborted` 禁用重新解析、重新审查、人工复核提交和报告生成。

动作权限：

- `parsed`: 可启动清洗与向量审查。
- `scanning`: 可查看真实 pipeline；只有 stale/failed 时允许重新启动。
- `hitl_*`: 可执行人工复核。
- `completed` / `report_ready`: 只允许查看和下载结果。

显示规则：

- 没有后端 `scan_progress` 时，不显示模拟维度。
- 没有 `ReviewItem` 时，不显示空规则列表；展示“尚未生成审查项”和具体 pipeline 原因。
- 有 `ReviewItem` 时，右栏进入规则审查项模式。

## PDF 与证据定位

当前阶段支持：

- 浏览器原生 PDF 渲染。
- MinerU 解析证据块高亮。
- 按规则证据跳转页码。
- 展示 `block_id`、`chunk_id`、`bbox`、`page_range`。

当前阶段不支持：

- 原始 PDF bbox overlay。
- 在 PDF 上画框表示命中区域。
- 声称“精准高亮原 PDF”。

原因：MinerU bbox 到浏览器 PDF 画布的坐标投影需要单独验证 page size、cropbox、rotation、缩放和坐标原点。没有验证前上线会误导审查人员。

## 错误处理

1. `source_pdf_url` 不存在：
   - 自动降级为解析证据视图。
   - 不报错，不阻塞工作台。

2. `document-content` 不存在：
   - 显示“尚未生成解析结果”。
   - 如果 session 可重试，给出重试解析入口。

3. pipeline stale：
   - 显示最后更新阶段、更新时间和失败原因。
   - 允许重新启动清洗与审查。

4. 规则审查失败：
   - 显示后端 `last_failure`。
   - 不伪装成 MinerU 解析失败。

5. session aborted：
   - 所有动作按钮禁用。
   - 查看入口保留。

## 测试策略

后端：

- `document-content` 返回 `source_pdf_url`。
- PDF 源文件接口只服务 PDF。
- 非 PDF / 文件缺失返回 404。
- aborted session 仍能读取 document-content。
- scanning stale 能显示失败阶段并允许重启。

前端：

- `/document`、`/fields`、`/scanning`、`/review` 都进入统一工作台。
- PDF session 默认显示原始 PDF。
- JSON session 自动显示解析证据视图。
- aborted session 可以查看但不能操作。
- scanning 没有审查项时显示 pipeline 原因。
- review 有审查项时显示规则审查右栏。

构建：

- `npm run build`
- 后端 targeted pytest
- `python -m compileall app`

## 实施分阶段

### 阶段 1：工作台壳

新增 `ReviewWorkspacePage` 和 `ReviewWorkspaceShell`，让 `/document` 先接入统一三栏结构。

### 阶段 2：文档视图拆分

拆出 `DocumentNavigator`、`DocumentViewer`、`ParsedEvidenceView`，从 `HITLReviewPage` 移除重复文档渲染代码。

### 阶段 3：阶段面板接入

把 document、fields、scanning、review 四种 mode 接入右栏。

### 阶段 4：路由统一

让现有页面成为 wrapper 或直接改路由到 `ReviewWorkspacePage`。

### 阶段 5：清理旧页面

确认无入口依赖后删除或瘦身 `ParsedDocumentPage`、`AIScanningPage`、`FieldVerificationPage` 中重复的文档查看逻辑。

## 子 Agent 拆分建议

实现阶段可以拆成 3 个并行子任务：

1. 前端组件拆分 Agent
   - 负责从 `HITLReviewPage` 提取通用组件。

2. 前端路由与状态 Agent
   - 负责 mode 推导、数据加载、只读权限和按钮状态。

3. 后端与测试 Agent
   - 负责补充接口测试、source PDF 安全边界、stale pipeline 状态测试。

主控 Agent 负责合并、冲突处理、端到端验证和最终提交。

## 验收标准

1. 从解析完成页点击“查看解析文档”，进入统一工作台。
2. 工作台中栏默认展示真实原始 PDF。
3. 可以切换到 MinerU 解析证据视图。
4. 同一工作台可以进入规则审查面板。
5. 已中止会话仍可进入查看，但所有写操作禁用。
6. 没有审查项时，不显示模拟维度或假勾选。
7. 清洗/向量/规则审查失败时显示真实失败原因。
8. JSON 上传场景没有原 PDF 时不报错，自动显示解析证据。
9. `HITLReviewPage` 不再继续膨胀为所有逻辑混杂的巨型页面。
10. 构建和 targeted tests 通过。
