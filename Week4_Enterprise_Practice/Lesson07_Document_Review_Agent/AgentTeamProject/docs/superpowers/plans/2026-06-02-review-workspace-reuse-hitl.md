# Review Workspace Reuse HITL Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reuse the existing `HITLReviewPage` working model as a unified document review workspace for parsed document viewing, extracted field review, scan progress, and manual rule review.

**Architecture:** Keep the current backend review pipeline and MinerU parsing chain unchanged. Create a front-end workspace shell with shared document navigation/viewing and a mode-specific right panel; route `/document`, `/fields`, `/scanning`, and `/review` into this shared workspace while preserving existing URLs. Backend changes stay limited to source PDF/document-content/stale scan verification if a targeted test exposes a gap.

**Tech Stack:** FastAPI + SQLAlchemy backend, React 18 + Vite frontend, TypeScript, Tailwind utility classes, existing API clients in `frontend/src/app/api`, targeted `uv run pytest`, `python -m compileall app`, `npm run build`.

---

## Success Criteria

1. `/contracts/:id/document`, `/contracts/:id/fields`, `/contracts/:id/scanning`, and `/contracts/:id/review` render the same three-column workspace shell.
2. The middle column defaults to the original PDF iframe when `document-content.source_pdf_url` exists.
3. JSON/DOCX sessions without `source_pdf_url` automatically show MinerU parsed evidence instead of failing.
4. Parsed evidence view shows page, block type, text/html/image path, block id, section hint, and bbox when present.
5. The right panel changes by workspace mode: document summary, extracted fields, scan pipeline, or review issues.
6. `aborted` sessions remain viewable but all write actions in fields, scan restart, and manual review are disabled.
7. The scanning panel never displays simulated dimensions or automatic checkmarks; it shows backend pipeline stages, cached/completed/running/failed status, real failure messages, and generated review-item counts.
8. Existing review decision behavior in `HITLReviewPage` is preserved after moving it behind the workspace shell.
9. No file view action triggers PDF upload, MinerU parse, field extraction, vector rebuild, RAG retrieval, or rule judgement.
10. Targeted backend tests, backend compile, and frontend build pass.

## File Structure

### Create

- `frontend/src/app/pages/ReviewWorkspacePage.tsx`
  - Owns `sessionId`, derives mode from route path, loads shared data, and passes it to shell slots.
- `frontend/src/app/reviewWorkspace/types.ts`
  - Defines `ReviewWorkspaceMode`, `WorkspaceData`, `WorkspaceLoadState`, and shared callback types.
- `frontend/src/app/reviewWorkspace/mode.ts`
  - Pure helpers for route-to-mode, mode labels, and read/write permissions.
- `frontend/src/app/reviewWorkspace/document.ts`
  - Pure helpers for page selection, block count, PDF URL construction, and first evidence page lookup.
- `frontend/src/app/reviewWorkspace/components/ReviewWorkspaceShell.tsx`
  - Three-column layout only; no data fetching.
- `frontend/src/app/reviewWorkspace/components/DocumentNavigator.tsx`
  - Left column page list, outline, workflow status summary, and quick stage links.
- `frontend/src/app/reviewWorkspace/components/DocumentViewer.tsx`
  - Middle column original PDF / parsed evidence toggle.
- `frontend/src/app/reviewWorkspace/components/ParsedEvidenceView.tsx`
  - Renders parsed document blocks from `ReviewDocumentContentResponse`.
- `frontend/src/app/reviewWorkspace/components/WorkspaceStagePanel.tsx`
  - Right column mode switcher.
- `frontend/src/app/reviewWorkspace/components/FieldsStagePanel.tsx`
  - Reuses existing field API behavior in workspace form.
- `frontend/src/app/reviewWorkspace/components/ScanningStagePanel.tsx`
  - Shows real `review-pipeline-status`, poll status, failure reason, and restart only when allowed.
- `frontend/src/app/reviewWorkspace/components/ReviewIssuePanel.tsx`
  - Extracts the review item list/decision panel behavior from `HITLReviewPage`.

### Modify

- `frontend/src/app/routes.tsx`
  - Point document/fields/scanning/review routes to `ReviewWorkspacePage`.
- `frontend/src/app/pages/HITLReviewPage.tsx`
  - Convert to a wrapper around `ReviewWorkspacePage` or shrink it after `ReviewIssuePanel` extraction.
- `frontend/src/app/pages/ParsedDocumentPage.tsx`
  - Convert to a wrapper around `ReviewWorkspacePage` after document mode is stable.
- `frontend/src/app/pages/FieldVerificationPage.tsx`
  - Convert to a wrapper around `ReviewWorkspacePage` after fields mode is stable.
- `frontend/src/app/pages/AIScanningPage.tsx`
  - Convert to a wrapper around `ReviewWorkspacePage` after scanning mode is stable.
- `frontend/src/app/api/sessions.ts`
  - Only adjust types if current `ReviewPipelineStatusResponse`, `ReviewDocumentContentResponse`, or `SessionResponse` are missing fields used by the workspace.
- `backend/tests/test_session_document_content.py`
  - Keep or add source PDF / aborted view tests if current coverage is missing.
- `backend/tests/test_hitl_scan_progress.py`
  - Keep or add stale scanning / failure visibility tests if current coverage is missing.

### Do Not Modify Unless A Test Proves It Is Needed

- `backend/app/services/water_review_service.py`
- `backend/app/services/document_parse_worker.py`
- `backend/app/services/mineru_service.py`
- `backend/contract_review.db`

## Task 1: Backend Contract Guardrails

**Files:**
- Test: `backend/tests/test_session_document_content.py`
- Test: `backend/tests/test_hitl_scan_progress.py`
- Modify only if failing: `backend/app/api/sessions.py`

- [ ] **Step 1: Run current targeted backend tests**

```bash
cd backend
uv run pytest tests/test_session_document_content.py tests/test_hitl_scan_progress.py -q
```

Expected: all existing tests pass. If they fail, record the exact failing assertion before editing.

- [ ] **Step 2: Add missing source PDF and aborted-view assertions only if absent**

In `backend/tests/test_session_document_content.py`, ensure these behaviors are covered by existing test names or add focused tests:

```python
def test_document_content_can_read_mineru_artifact_before_review_pipeline(client, parsed_session):
    response = client.get(f"/api/v1/sessions/{parsed_session.id}/document-content")
    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == str(parsed_session.id)
    assert payload["pages"]
    assert "source_pdf_url" in payload


def test_session_source_file_serves_original_pdf(client, parsed_pdf_session):
    response = client.get(f"/api/v1/sessions/{parsed_pdf_session.id}/source-file")
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")


def test_session_source_file_rejects_non_pdf_contract(client, parsed_json_session):
    response = client.get(f"/api/v1/sessions/{parsed_json_session.id}/source-file")
    assert response.status_code == 404
```

Use the repo's actual fixtures and helpers already present in this test file. Do not create a broad integration fixture if local factories already exist.

- [ ] **Step 3: Verify stale scan/failure contract**

In `backend/tests/test_hitl_scan_progress.py`, ensure the API returns `last_failure` and stage statuses without needing SSE:

```python
def test_review_pipeline_status_exposes_last_failure(client, scanning_session_with_failed_stage):
    response = client.get(f"/api/v1/sessions/{scanning_session_with_failed_stage.id}/review-pipeline-status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["last_failure"]["user_message"]
    assert any(stage["status"] in {"failed", "running", "completed", "cached", "skipped"} for stage in payload["stages"])
```

Use existing fixture names if they differ; keep the assertion behavior identical.

- [ ] **Step 4: Run backend guardrail tests**

```bash
cd backend
uv run pytest tests/test_session_document_content.py tests/test_hitl_scan_progress.py -q
```

Expected: pass.

- [ ] **Step 5: Commit if backend code or tests changed**

```bash
git add backend/tests/test_session_document_content.py backend/tests/test_hitl_scan_progress.py backend/app/api/sessions.py
git commit -m "test: guard review workspace backend contracts"
```

Do not add `backend/contract_review.db`.

## Task 2: Workspace Pure Helpers

**Files:**
- Create: `frontend/src/app/reviewWorkspace/types.ts`
- Create: `frontend/src/app/reviewWorkspace/mode.ts`
- Create: `frontend/src/app/reviewWorkspace/document.ts`

- [ ] **Step 1: Create shared workspace types**

Create `frontend/src/app/reviewWorkspace/types.ts`:

```ts
import type {
  LangExtractFactsResponse,
  ReviewDocumentContentResponse,
  ReviewPipelineStatusResponse,
  ReviewRuleTopicsResponse,
  SessionResponse,
} from '../api/sessions';
import type { ReviewItem } from '../types';

export type ReviewWorkspaceMode = 'document' | 'fields' | 'scanning' | 'review';
export type ViewerMode = 'pdf' | 'parsed';

export interface WorkspaceLoadState {
  session: boolean;
  document: boolean;
  fields: boolean;
  pipeline: boolean;
  items: boolean;
  ruleTopics: boolean;
  facts: boolean;
}

export interface WorkspaceData {
  session: SessionResponse | null;
  documentContent: ReviewDocumentContentResponse | null;
  pipelineStatus: ReviewPipelineStatusResponse | null;
  facts: LangExtractFactsResponse | null;
  items: ReviewItem[];
  ruleTopics: ReviewRuleTopicsResponse | null;
}
```

- [ ] **Step 2: Create route and permission helpers**

Create `frontend/src/app/reviewWorkspace/mode.ts`:

```ts
import type { SessionResponse } from '../api/sessions';
import type { ReviewWorkspaceMode } from './types';

export function modeFromPath(pathname: string): ReviewWorkspaceMode {
  if (pathname.endsWith('/fields')) return 'fields';
  if (pathname.endsWith('/scanning')) return 'scanning';
  if (pathname.endsWith('/review')) return 'review';
  return 'document';
}

export function modeTitle(mode: ReviewWorkspaceMode): string {
  if (mode === 'fields') return '关键信息';
  if (mode === 'scanning') return '清洗与规则审查';
  if (mode === 'review') return '人工复核';
  return '解析文档';
}

export function modeDescription(mode: ReviewWorkspaceMode): string {
  if (mode === 'fields') return '查看并核对从文档中抽取出的项目名称、面积、土石方、投资等关键信息。';
  if (mode === 'scanning') return '查看数据清洗、向量索引、RAG 检索和规则判定的真实后端状态。';
  if (mode === 'review') return '查看规则命中、证据来源和人工复核动作。';
  return '查看原始 PDF 和 MinerU 已生成的结构化解析结果。';
}

export function isReadOnlySession(session: SessionResponse | null): boolean {
  return Boolean(session?.read_only || session?.state === 'aborted');
}

export function canStartReview(session: SessionResponse | null): boolean {
  return Boolean(session && !isReadOnlySession(session) && session.state === 'parsed');
}

export function canRestartReview(session: SessionResponse | null, hasFailure: boolean): boolean {
  if (!session || isReadOnlySession(session)) return false;
  return session.state === 'parsed' || (session.state === 'scanning' && hasFailure);
}

export function canReviewItems(session: SessionResponse | null): boolean {
  if (!session || isReadOnlySession(session)) return false;
  return session.state === 'hitl_pending' || session.state === 'hitl_high_risk' || session.state === 'hitl_medium_confirm';
}
```

- [ ] **Step 3: Create document helpers**

Create `frontend/src/app/reviewWorkspace/document.ts`:

```ts
import { API_BASE_URL } from '../api/client';
import type { ReviewDocumentContentResponse, ReviewDocumentPage } from '../api/sessions';

export function countDocumentBlocks(content: ReviewDocumentContentResponse | null): number {
  return content?.pages.reduce((total, page) => total + page.blocks.length, 0) ?? 0;
}

export function firstPageNumber(content: ReviewDocumentContentResponse | null): number {
  return content?.pages[0]?.page_number ?? 1;
}

export function findPage(content: ReviewDocumentContentResponse | null, pageNumber: number): ReviewDocumentPage | null {
  return content?.pages.find((page) => page.page_number === pageNumber) ?? content?.pages[0] ?? null;
}

export function resolveSessionFileUrl(path?: string): string {
  const value = path?.trim();
  if (!value) return '';
  if (/^https?:\/\//i.test(value)) return value;
  try {
    return new URL(value, API_BASE_URL).toString();
  } catch {
    return value;
  }
}

export function pdfFrameUrl(path: string | undefined, page: number): string {
  const url = resolveSessionFileUrl(path);
  if (!url) return '';
  const [base] = url.split('#');
  return `${base}#page=${Math.max(1, page)}&zoom=page-width`;
}
```

- [ ] **Step 4: Run TypeScript build to catch type errors**

```bash
cd frontend
npm run build
```

Expected: build passes or fails only on the current file import path being unused. Remove unused imports if the build reports them.

- [ ] **Step 5: Commit helper files**

```bash
git add frontend/src/app/reviewWorkspace/types.ts frontend/src/app/reviewWorkspace/mode.ts frontend/src/app/reviewWorkspace/document.ts
git commit -m "feat: add review workspace helpers"
```

## Task 3: Shared Document Viewer Components

**Files:**
- Create: `frontend/src/app/reviewWorkspace/components/ParsedEvidenceView.tsx`
- Create: `frontend/src/app/reviewWorkspace/components/DocumentViewer.tsx`
- Create: `frontend/src/app/reviewWorkspace/components/DocumentNavigator.tsx`
- Create: `frontend/src/app/reviewWorkspace/components/ReviewWorkspaceShell.tsx`

- [ ] **Step 1: Create parsed evidence view**

Create `frontend/src/app/reviewWorkspace/components/ParsedEvidenceView.tsx`:

```tsx
import { FileText, Image as ImageIcon } from 'lucide-react';
import type { ReviewDocumentBlock, ReviewDocumentPage } from '../../api/sessions';

function blockLabel(type: string) {
  if (type === 'title') return '标题';
  if (type === 'table') return '表格';
  if (type === 'image') return '图片';
  return '正文';
}

export function ParsedEvidenceView({ page }: { page: ReviewDocumentPage | null }) {
  if (!page) {
    return <div className="p-4 text-sm text-slate-500">暂无可展示的解析块。</div>;
  }
  return (
    <div className="space-y-3 p-4">
      {page.blocks.map((block, index) => (
        <ParsedBlockCard key={block.block_id || `${page.page_number}-${index}`} block={block} />
      ))}
    </div>
  );
}

function ParsedBlockCard({ block }: { block: ReviewDocumentBlock }) {
  const hasImage = Boolean(block.image_path);
  return (
    <article className="rounded-md border border-slate-100 bg-slate-50 p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        <span className="inline-flex items-center gap-1 rounded-full bg-white px-2 py-0.5">
          {hasImage ? <ImageIcon className="h-3.5 w-3.5" /> : <FileText className="h-3.5 w-3.5" />}
          {blockLabel(block.type)}
        </span>
        <span className="break-all">{block.block_id}</span>
        {block.section_hint ? <span>{block.section_hint}</span> : null}
      </div>
      {block.text ? <p className="whitespace-pre-wrap text-sm leading-7 text-slate-800">{block.text}</p> : null}
      {block.html ? (
        <pre className="mt-2 max-h-56 overflow-auto rounded-md bg-white p-3 text-xs leading-5 text-slate-600">
          {block.html}
        </pre>
      ) : null}
      {hasImage ? (
        <div className="mt-3">
          {block.image_path?.startsWith('/api/') || block.image_path?.startsWith('http') ? (
            <img src={block.image_path} alt={block.text || block.block_id} className="max-h-[520px] max-w-full rounded-md border border-slate-200 bg-white object-contain" />
          ) : null}
          <p className="mt-1 break-all text-xs text-slate-500">{block.image_path}</p>
        </div>
      ) : null}
      {block.bbox?.length ? <p className="mt-2 text-xs text-slate-400">bbox: {block.bbox.join(', ')}</p> : null}
    </article>
  );
}
```

- [ ] **Step 2: Create document viewer**

Create `frontend/src/app/reviewWorkspace/components/DocumentViewer.tsx`:

```tsx
import type { ViewerMode } from '../types';
import type { ReviewDocumentContentResponse, ReviewDocumentPage } from '../../api/sessions';
import { pdfFrameUrl } from '../document';
import { ParsedEvidenceView } from './ParsedEvidenceView';

interface DocumentViewerProps {
  content: ReviewDocumentContentResponse | null;
  activePage: ReviewDocumentPage | null;
  activePageNumber: number;
  viewerMode: ViewerMode;
  onViewerModeChange: (mode: ViewerMode) => void;
}

export function DocumentViewer({
  content,
  activePage,
  activePageNumber,
  viewerMode,
  onViewerModeChange,
}: DocumentViewerProps) {
  if (!content) {
    return <section className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-500">暂无可查看的解析文档。</section>;
  }

  const hasPdf = Boolean(content.source_pdf_url);
  const activeViewerMode: ViewerMode = hasPdf ? viewerMode : 'parsed';
  const pdfUrl = pdfFrameUrl(content.source_pdf_url, activePageNumber);

  return (
    <section className="min-w-0 rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <div>
          <h2 className="text-sm font-semibold text-slate-950">第 {activePage?.page_number ?? activePageNumber} 页</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            {activeViewerMode === 'pdf'
              ? '浏览器原生渲染原始 PDF；证据定位请切换到解析视图。'
              : '按 MinerU 解析块顺序展示文本、表格和图片引用。'}
          </p>
        </div>
        {hasPdf ? (
          <div className="flex rounded border border-slate-200 bg-slate-50 p-0.5 text-xs">
            <button type="button" onClick={() => onViewerModeChange('pdf')} className={`rounded px-2 py-1 ${activeViewerMode === 'pdf' ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-white'}`}>
              原始PDF
            </button>
            <button type="button" onClick={() => onViewerModeChange('parsed')} className={`rounded px-2 py-1 ${activeViewerMode === 'parsed' ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-white'}`}>
              解析证据
            </button>
          </div>
        ) : null}
      </div>
      {activeViewerMode === 'pdf' && pdfUrl ? (
        <iframe key={pdfUrl} title={`${content.title} 原始PDF`} src={pdfUrl} className="h-[calc(100vh-230px)] min-h-[760px] w-full border-0 bg-white" />
      ) : (
        <ParsedEvidenceView page={activePage} />
      )}
    </section>
  );
}
```

- [ ] **Step 3: Create navigator and shell**

Create `frontend/src/app/reviewWorkspace/components/DocumentNavigator.tsx` and `ReviewWorkspaceShell.tsx` with no data fetching:

```tsx
// DocumentNavigator.tsx
import type { ReviewDocumentContentResponse } from '../../api/sessions';
import type { ReviewWorkspaceMode } from '../types';
import { countDocumentBlocks } from '../document';
import { modeTitle } from '../mode';

interface DocumentNavigatorProps {
  mode: ReviewWorkspaceMode;
  content: ReviewDocumentContentResponse | null;
  activePageNumber: number;
  onPageChange: (page: number) => void;
}

export function DocumentNavigator({ mode, content, activePageNumber, onPageChange }: DocumentNavigatorProps) {
  return (
    <aside className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm lg:sticky lg:top-[130px] lg:max-h-[calc(100vh-150px)] lg:overflow-auto">
      <div className="mb-3">
        <p className="text-xs text-slate-500">当前环节</p>
        <h2 className="text-sm font-semibold text-slate-950">{modeTitle(mode)}</h2>
        <p className="mt-2 text-xs text-slate-500">页数：{content?.page_count ?? '-'} · 解析块：{countDocumentBlocks(content) || '-'}</p>
      </div>
      <div className="grid grid-cols-3 gap-2 lg:grid-cols-1">
        {(content?.pages ?? []).map((page) => (
          <button
            key={page.page_number}
            type="button"
            onClick={() => onPageChange(page.page_number)}
            className={`rounded-md border px-3 py-2 text-left text-sm transition-colors ${
              page.page_number === activePageNumber
                ? 'border-blue-300 bg-blue-50 text-blue-700'
                : 'border-slate-200 bg-white text-slate-600 hover:bg-slate-50'
            }`}
          >
            第 {page.page_number} 页
            <span className="ml-1 text-xs text-slate-400">{page.blocks.length} 块</span>
          </button>
        ))}
      </div>
    </aside>
  );
}
```

```tsx
// ReviewWorkspaceShell.tsx
import type { ReactNode } from 'react';
import { GlobalNav } from '../../components/GlobalNav';
import { WorkflowStatusBar } from '../../components/WorkflowStatusBar';
import type { SessionState } from '../../types';

interface ReviewWorkspaceShellProps {
  sessionState: SessionState;
  scanningStarted?: boolean;
  header: ReactNode;
  navigator: ReactNode;
  viewer: ReactNode;
  stagePanel: ReactNode;
}

export function ReviewWorkspaceShell({ sessionState, scanningStarted, header, navigator, viewer, stagePanel }: ReviewWorkspaceShellProps) {
  return (
    <div className="min-h-screen bg-slate-50">
      <GlobalNav />
      <WorkflowStatusBar sessionState={sessionState} scanningStarted={scanningStarted} />
      <main className="pt-[118px]">
        <div className="mx-auto max-w-[1760px] px-4 py-6 sm:px-6 lg:px-8">
          {header}
          <div className="grid gap-4 xl:grid-cols-[260px_minmax(0,1fr)_420px]">
            {navigator}
            {viewer}
            {stagePanel}
          </div>
        </div>
      </main>
    </div>
  );
}
```

- [ ] **Step 4: Run frontend build**

```bash
cd frontend
npm run build
```

Expected: pass. If TypeScript complains about `React.ReactNode`, import `type React from 'react';` or `type { ReactNode } from 'react'` and use that exact type consistently.

- [ ] **Step 5: Commit shared viewer components**

```bash
git add frontend/src/app/reviewWorkspace/components/ParsedEvidenceView.tsx frontend/src/app/reviewWorkspace/components/DocumentViewer.tsx frontend/src/app/reviewWorkspace/components/DocumentNavigator.tsx frontend/src/app/reviewWorkspace/components/ReviewWorkspaceShell.tsx
git commit -m "feat: add shared review workspace document viewer"
```

## Task 4: Workspace Page and Document Mode

**Files:**
- Create: `frontend/src/app/pages/ReviewWorkspacePage.tsx`
- Modify: `frontend/src/app/routes.tsx`

- [ ] **Step 1: Implement workspace data loading for document mode**

Create `frontend/src/app/pages/ReviewWorkspacePage.tsx`:

```tsx
import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router';
import { ArrowLeft, Loader2 } from 'lucide-react';
import { getReviewDocumentContent, getSession } from '../api/sessions';
import type { ReviewDocumentContentResponse, SessionResponse } from '../api/sessions';
import type { SessionState } from '../types';
import { DocumentNavigator } from '../reviewWorkspace/components/DocumentNavigator';
import { DocumentViewer } from '../reviewWorkspace/components/DocumentViewer';
import { ReviewWorkspaceShell } from '../reviewWorkspace/components/ReviewWorkspaceShell';
import { findPage, firstPageNumber } from '../reviewWorkspace/document';
import { modeDescription, modeFromPath, modeTitle } from '../reviewWorkspace/mode';
import type { ReviewWorkspaceMode, ViewerMode } from '../reviewWorkspace/types';

export function ReviewWorkspacePage() {
  const { id: sessionId } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const mode = modeFromPath(location.pathname);
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [content, setContent] = useState<ReviewDocumentContentResponse | null>(null);
  const [activePage, setActivePage] = useState(1);
  const [viewerMode, setViewerMode] = useState<ViewerMode>('pdf');
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    if (!sessionId) return;
    setIsLoading(true);
    Promise.allSettled([getSession(sessionId), getReviewDocumentContent(sessionId)])
      .then(([sessionResult, contentResult]) => {
        if (sessionResult.status === 'fulfilled') setSession(sessionResult.value);
        if (contentResult.status === 'fulfilled') {
          setContent(contentResult.value);
          setActivePage(firstPageNumber(contentResult.value));
          setViewerMode(contentResult.value.source_pdf_url ? 'pdf' : 'parsed');
          setLoadError('');
        } else {
          setContent(null);
          setViewerMode('parsed');
          setLoadError(contentResult.reason?.message || '解析文档读取失败');
        }
      })
      .finally(() => setIsLoading(false));
  }, [sessionId]);

  const currentPage = useMemo(() => findPage(content, activePage), [content, activePage]);
  const state = (session?.state || 'parsed') as SessionState;

  const header = (
    <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <button type="button" onClick={() => navigate('/contracts')} className="mb-3 inline-flex items-center gap-2 text-sm text-slate-500 hover:text-slate-800">
          <ArrowLeft className="h-4 w-4" />
          返回方案列表
        </button>
        <h1 className="text-xl font-semibold text-slate-950">{modeTitle(mode)}</h1>
        <p className="mt-1 text-sm text-slate-600">{modeDescription(mode)}</p>
      </div>
      <ModeLinks sessionId={sessionId || ''} mode={mode} />
    </div>
  );

  if (isLoading) {
    return (
      <ReviewWorkspaceShell
        sessionState={state}
        header={header}
        navigator={<div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-500">正在加载</div>}
        viewer={<div className="flex items-center justify-center rounded-lg border border-slate-200 bg-white py-20 text-slate-500"><Loader2 className="mr-2 h-5 w-5 animate-spin" />正在读取工作台数据</div>}
        stagePanel={<div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-500">等待数据</div>}
      />
    );
  }

  return (
    <ReviewWorkspaceShell
      sessionState={state}
      scanningStarted={state === 'scanning'}
      header={header}
      navigator={<DocumentNavigator mode={mode} content={content} activePageNumber={activePage} onPageChange={setActivePage} />}
      viewer={loadError ? <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">{loadError}</div> : <DocumentViewer content={content} activePage={currentPage} activePageNumber={activePage} viewerMode={viewerMode} onViewerModeChange={setViewerMode} />}
      stagePanel={<DocumentModePanel sessionId={sessionId || ''} content={content} mode={mode} />}
    />
  );
}

function ModeLinks({ sessionId, mode }: { sessionId: string; mode: ReviewWorkspaceMode }) {
  const links: Array<[ReviewWorkspaceMode, string]> = [
    ['document', '解析文档'],
    ['fields', '关键信息'],
    ['scanning', '清洗审查'],
    ['review', '人工复核'],
  ];
  return (
    <div className="flex flex-wrap gap-2">
      {links.map(([targetMode, label]) => {
        const path = targetMode === 'document' ? 'document' : targetMode;
        return (
          <a key={targetMode} href={`/contracts/${sessionId}/${path}`} className={`rounded-md border px-3 py-2 text-sm ${targetMode === mode ? 'border-slate-900 bg-slate-900 text-white' : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'}`}>
            {label}
          </a>
        );
      })}
    </div>
  );
}

function DocumentModePanel({ sessionId, content, mode }: { sessionId: string; content: ReviewDocumentContentResponse | null; mode: ReviewWorkspaceMode }) {
  return (
    <aside className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-xs text-slate-500">当前面板</p>
      <h2 className="mt-1 text-base font-semibold text-slate-950">{modeTitle(mode)}</h2>
      <div className="mt-4 space-y-2 text-sm text-slate-600">
        <p>页数：{content?.page_count ?? '-'}</p>
        <p>来源：{content?.source ?? '-'}</p>
        <p>原始 PDF：{content?.source_pdf_url ? '可查看' : '无'}</p>
      </div>
      <button type="button" onClick={() => window.location.assign(`/contracts/${sessionId}/scanning`)} className="mt-4 inline-flex h-10 w-full items-center justify-center rounded-md bg-slate-900 px-3 text-sm font-medium text-white hover:bg-slate-800">
        进入清洗与规则审查
      </button>
    </aside>
  );
}
```

- [ ] **Step 2: Route only `/document` to the workspace first**

Modify `frontend/src/app/routes.tsx`:

```tsx
import { ReviewWorkspacePage } from './pages/ReviewWorkspacePage';
```

Replace only this route:

```tsx
{ path: '/contracts/:id/document', Component: ReviewWorkspacePage },
```

- [ ] **Step 3: Run frontend build**

```bash
cd frontend
npm run build
```

Expected: pass.

- [ ] **Step 4: Browser smoke for document route**

Open a known parsed session:

```text
http://127.0.0.1:5173/contracts/267d9e3c-322b-4828-898b-8ff1a0e00854/document
```

Expected: same workspace shell appears, PDF iframe appears when the backend has `source_pdf_url`, and switching to parsed evidence does not start network calls to `/contracts/upload`, MinerU, or `/start-review`.

- [ ] **Step 5: Commit document workspace route**

```bash
git add frontend/src/app/pages/ReviewWorkspacePage.tsx frontend/src/app/routes.tsx
git commit -m "feat: route parsed document into review workspace"
```

## Task 5: Stage Panels for Fields and Scanning

**Files:**
- Create: `frontend/src/app/reviewWorkspace/components/FieldsStagePanel.tsx`
- Create: `frontend/src/app/reviewWorkspace/components/ScanningStagePanel.tsx`
- Create: `frontend/src/app/reviewWorkspace/components/WorkspaceStagePanel.tsx`
- Modify: `frontend/src/app/pages/ReviewWorkspacePage.tsx`
- Modify: `frontend/src/app/routes.tsx`

- [ ] **Step 1: Create fields panel using existing APIs**

Create `frontend/src/app/reviewWorkspace/components/FieldsStagePanel.tsx`:

```tsx
import { useEffect, useState, type ReactNode } from 'react';
import { CheckCircle, Edit2, Loader2, SkipForward } from 'lucide-react';
import { listFields, verifyField } from '../../api/fields';
import { ConfidenceBadge } from '../../components/ConfidenceBadge';
import type { ExtractedField, VerificationStatus } from '../../types';

interface FieldsStagePanelProps {
  sessionId: string;
  readOnly: boolean;
}

export function FieldsStagePanel({ sessionId, readOnly }: FieldsStagePanelProps) {
  const [fields, setFields] = useState<(ExtractedField & { editValue?: string })[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    setIsLoading(true);
    listFields(sessionId)
      .then((res) => {
        setFields(res.items.map((field) => ({ ...field, editValue: field.field_value })));
        setError('');
      })
      .catch((err) => setError(err.message || '加载字段失败'))
      .finally(() => setIsLoading(false));
  }, [sessionId]);

  const handleAction = async (field: ExtractedField & { editValue?: string }, action: VerificationStatus) => {
    if (readOnly) return;
    const verifiedValue = action === 'modified' ? field.editValue || field.field_value : field.field_value;
    const apiAction = action === 'confirmed' ? 'confirm' : action === 'modified' ? 'modify' : 'skip';
    setFields((prev) => prev.map((item) => item.id === field.id ? { ...item, field_value: verifiedValue, verification_status: action } : item));
    await verifyField(sessionId, field.id, { action: apiAction, verified_value: verifiedValue });
  };

  if (isLoading) return <PanelFrame title="关键信息"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></PanelFrame>;
  if (error) return <PanelFrame title="关键信息"><p className="text-sm text-red-600">{error}</p></PanelFrame>;

  return (
    <PanelFrame title="关键信息">
      {readOnly ? <p className="mb-3 rounded-md bg-slate-50 p-2 text-xs text-slate-500">当前会话只读，字段不可修改。</p> : null}
      <div className="space-y-3">
        {fields.length ? fields.map((field) => (
          <div key={field.id} className="rounded-md border border-slate-200 p-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-sm font-medium text-slate-900">{field.field_label || field.field_name}</p>
                <input
                  value={field.editValue ?? field.field_value}
                  disabled={readOnly}
                  onChange={(event) => setFields((prev) => prev.map((item) => item.id === field.id ? { ...item, editValue: event.target.value } : item))}
                  className="mt-2 w-full rounded-md border border-slate-200 px-2 py-1 text-sm disabled:bg-slate-50"
                />
              </div>
              <ConfidenceBadge score={field.confidence_score} needsVerification={field.needs_human_verification} />
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-500">第 {field.source_page_number} 页：{field.source_evidence_text}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button disabled={readOnly} onClick={() => handleAction(field, 'confirmed')} className="inline-flex items-center gap-1 rounded border border-green-200 px-2 py-1 text-xs text-green-700 disabled:opacity-50"><CheckCircle className="h-3 w-3" />确认</button>
              <button disabled={readOnly} onClick={() => handleAction(field, 'modified')} className="inline-flex items-center gap-1 rounded border border-blue-200 px-2 py-1 text-xs text-blue-700 disabled:opacity-50"><Edit2 className="h-3 w-3" />保存修改</button>
              <button disabled={readOnly} onClick={() => handleAction(field, 'skipped')} className="inline-flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-xs text-slate-600 disabled:opacity-50"><SkipForward className="h-3 w-3" />跳过</button>
            </div>
          </div>
        )) : <p className="text-sm text-slate-500">暂无已抽取的关键信息。</p>}
      </div>
    </PanelFrame>
  );
}

function PanelFrame({ title, children }: { title: string; children: ReactNode }) {
  return <aside className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"><h2 className="mb-3 text-base font-semibold text-slate-950">{title}</h2>{children}</aside>;
}
```

- [ ] **Step 2: Create scanning panel using real pipeline status**

Create `frontend/src/app/reviewWorkspace/components/ScanningStagePanel.tsx`:

```tsx
import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, Loader2, RotateCcw } from 'lucide-react';
import { getReviewPipelineStatus, startReview, type ReviewPipelineStatusResponse, type SessionResponse } from '../../api/sessions';
import { listItems } from '../../api/items';
import type { ReviewItem } from '../../types';
import { canRestartReview } from '../mode';

export function ScanningStagePanel({ sessionId, session, readOnly }: { sessionId: string; session: SessionResponse | null; readOnly: boolean }) {
  const [status, setStatus] = useState<ReviewPipelineStatusResponse | null>(null);
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRestarting, setIsRestarting] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    const [pipelineRes, itemsRes] = await Promise.allSettled([
      getReviewPipelineStatus(sessionId),
      listItems(sessionId, { limit: 100 }),
    ]);
    if (pipelineRes.status === 'fulfilled') setStatus(pipelineRes.value);
    if (itemsRes.status === 'fulfilled') setItems(itemsRes.value.items);
    if (pipelineRes.status === 'rejected') setError(pipelineRes.reason?.message || '读取审查状态失败');
    setIsLoading(false);
  }, [sessionId]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const failureMessage = String(status?.last_failure?.user_message || status?.last_failure?.message || status?.last_failure?.error || '').trim();
  const canRestart = canRestartReview(session, Boolean(failureMessage)) && !readOnly;

  const restart = async () => {
    if (!canRestart) return;
    setIsRestarting(true);
    setError('');
    try {
      await startReview(sessionId);
      await refresh();
    } catch (err: any) {
      setError(err.message || '重新启动失败');
    } finally {
      setIsRestarting(false);
    }
  };

  return (
    <aside className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-slate-950">清洗与规则审查</h2>
          <p className="mt-1 text-xs text-slate-500">仅展示后端真实 pipeline，不显示模拟维度。</p>
        </div>
        {isLoading ? <Loader2 className="h-5 w-5 animate-spin text-slate-400" /> : null}
      </div>
      {error ? <p className="mt-3 rounded-md bg-red-50 p-2 text-sm text-red-700">{error}</p> : null}
      {failureMessage ? <p className="mt-3 rounded-md bg-amber-50 p-2 text-sm text-amber-800"><AlertCircle className="mr-1 inline h-4 w-4" />{failureMessage}</p> : null}
      <div className="mt-4 space-y-2">
        {(status?.stages ?? []).map((stage) => (
          <div key={stage.id} className="rounded-md border border-slate-200 p-3">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-slate-900">{stage.title}</p>
              <span className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600">{stage.status}</span>
            </div>
            <p className="mt-1 text-xs text-slate-500">{stage.message}</p>
            <p className="mt-1 text-xs text-slate-400">耗时：{stage.duration_ms ?? '-'} ms · 产物：{stage.artifact_exists ? '存在' : '无'} · 缓存：{stage.cache_reusable ? '可复用' : '不可复用'}</p>
          </div>
        ))}
      </div>
      <p className="mt-4 text-sm text-slate-600">已生成审查项：{items.length}</p>
      <button disabled={!canRestart || isRestarting} onClick={restart} className="mt-3 inline-flex h-10 w-full items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50">
        {isRestarting ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
        重新启动清洗与审查
      </button>
    </aside>
  );
}
```

- [ ] **Step 3: Create workspace stage switcher**

Create `frontend/src/app/reviewWorkspace/components/WorkspaceStagePanel.tsx`:

```tsx
import type { ReviewDocumentContentResponse, SessionResponse } from '../../api/sessions';
import type { ReviewWorkspaceMode } from '../types';
import { canStartReview, isReadOnlySession } from '../mode';
import { FieldsStagePanel } from './FieldsStagePanel';
import { ScanningStagePanel } from './ScanningStagePanel';

export function WorkspaceStagePanel({
  mode,
  sessionId,
  session,
  content,
  onStartReview,
}: {
  mode: ReviewWorkspaceMode;
  sessionId: string;
  session: SessionResponse | null;
  content: ReviewDocumentContentResponse | null;
  onStartReview: () => void;
}) {
  const readOnly = isReadOnlySession(session);
  if (mode === 'fields') return <FieldsStagePanel sessionId={sessionId} readOnly={readOnly} />;
  if (mode === 'scanning') return <ScanningStagePanel sessionId={sessionId} session={session} readOnly={readOnly} />;
  if (mode === 'review') return <aside className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"><h2 className="text-base font-semibold text-slate-950">人工复核</h2><p className="mt-2 text-sm text-slate-500">审查项将在下一任务接入。</p></aside>;

  return (
    <aside className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="text-base font-semibold text-slate-950">解析结果</h2>
      <div className="mt-4 space-y-2 text-sm text-slate-600">
        <p>页数：{content?.page_count ?? '-'}</p>
        <p>来源：{content?.source ?? '-'}</p>
        <p>原始 PDF：{content?.source_pdf_url ? '可查看' : '无'}</p>
      </div>
      {readOnly ? <p className="mt-4 rounded-md bg-slate-50 p-2 text-xs text-slate-500">当前会话只读，不能启动后续审查。</p> : null}
      <button disabled={!canStartReview(session)} onClick={onStartReview} className="mt-4 inline-flex h-10 w-full items-center justify-center rounded-md bg-slate-900 px-3 text-sm font-medium text-white hover:bg-slate-800 disabled:bg-slate-300">
        开始清洗与规则审查
      </button>
    </aside>
  );
}
```

- [ ] **Step 4: Wire fields and scanning routes**

Modify `ReviewWorkspacePage.tsx` to import `WorkspaceStagePanel` and `startReview`, replace `DocumentModePanel`, and route the start button to backend:

```tsx
import { getReviewDocumentContent, getSession, startReview } from '../api/sessions';
import { WorkspaceStagePanel } from '../reviewWorkspace/components/WorkspaceStagePanel';
```

Add:

```tsx
const handleStartReview = async () => {
  if (!sessionId) return;
  await startReview(sessionId);
  navigate(`/contracts/${sessionId}/scanning`);
};
```

Use:

```tsx
stagePanel={<WorkspaceStagePanel mode={mode} sessionId={sessionId || ''} session={session} content={content} onStartReview={handleStartReview} />}
```

Modify `routes.tsx`:

```tsx
{ path: '/contracts/:id/fields', Component: ReviewWorkspacePage },
{ path: '/contracts/:id/scanning', Component: ReviewWorkspacePage },
```

- [ ] **Step 5: Run frontend build**

```bash
cd frontend
npm run build
```

Expected: pass.

- [ ] **Step 6: Commit fields and scanning panels**

```bash
git add frontend/src/app/reviewWorkspace/components/FieldsStagePanel.tsx frontend/src/app/reviewWorkspace/components/ScanningStagePanel.tsx frontend/src/app/reviewWorkspace/components/WorkspaceStagePanel.tsx frontend/src/app/pages/ReviewWorkspacePage.tsx frontend/src/app/routes.tsx
git commit -m "feat: add fields and scanning workspace panels"
```

## Task 6: Review Issue Panel Extraction

**Files:**
- Create: `frontend/src/app/reviewWorkspace/components/ReviewIssuePanel.tsx`
- Modify: `frontend/src/app/pages/HITLReviewPage.tsx`
- Modify: `frontend/src/app/pages/ReviewWorkspacePage.tsx`
- Modify: `frontend/src/app/reviewWorkspace/components/WorkspaceStagePanel.tsx`
- Modify: `frontend/src/app/routes.tsx`

- [ ] **Step 1: Extract the smallest viable review issue panel**

Create `ReviewIssuePanel.tsx` by moving the review item loading and decision submission behavior from `HITLReviewPage.tsx`. Preserve these imports and behaviors:

```tsx
import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle, Loader2, XCircle } from 'lucide-react';
import { listItems, submitDecision } from '../../api/items';
import { RiskLevelBadge } from '../../components/RiskLevelBadge';
import { SourceBadge } from '../../components/SourceBadge';
import type { HumanDecision, ReviewItem, RiskLevel } from '../../types';

export function ReviewIssuePanel({ sessionId, readOnly, onEvidencePage }: { sessionId: string; readOnly: boolean; onEvidencePage: (page: number) => void }) {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  const [humanNote, setHumanNote] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    listItems(sessionId, { limit: 100 }).then((res) => {
      setItems(res.items);
      setActiveItemId(res.items.find((item) => item.human_decision === 'pending')?.id ?? res.items[0]?.id ?? null);
    });
  }, [sessionId]);

  const activeItem = items.find((item) => item.id === activeItemId) ?? null;

  useEffect(() => {
    const page = activeItem?.clause_location?.page_number || activeItem?.risk_evidence?.[0]?.page_number;
    if (page) onEvidencePage(page);
  }, [activeItem?.id]);

  const decide = async (decision: HumanDecision) => {
    if (!activeItem || readOnly) return;
    setIsSubmitting(true);
    try {
      await submitDecision(sessionId, activeItem.id, {
        decision,
        human_note: humanNote,
        edited_risk_level: activeItem.risk_level as RiskLevel,
        edited_finding: activeItem.ai_finding,
        is_false_positive: decision === 'reject',
      });
      setItems((prev) => prev.map((item) => item.id === activeItem.id ? { ...item, human_decision: decision, human_note: humanNote } : item));
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <aside className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="text-base font-semibold text-slate-950">人工复核</h2>
      {items.length === 0 ? <p className="mt-3 text-sm text-slate-500">尚未生成审查项。请先查看清洗与规则审查状态。</p> : null}
      <div className="mt-4 max-h-64 space-y-2 overflow-auto">
        {items.map((item) => (
          <button key={item.id} type="button" onClick={() => setActiveItemId(item.id)} className={`w-full rounded-md border p-3 text-left ${item.id === activeItemId ? 'border-blue-300 bg-blue-50' : 'border-slate-200 bg-white hover:bg-slate-50'}`}>
            <div className="flex items-center gap-2">
              <RiskLevelBadge level={item.risk_level} />
              <SourceBadge source={item.source_type} />
            </div>
            <p className="mt-2 line-clamp-2 text-sm text-slate-700">{item.ai_finding}</p>
          </button>
        ))}
      </div>
      {activeItem ? (
        <div className="mt-4 rounded-md border border-slate-200 p-3">
          <div className="mb-2 flex items-center gap-2 text-amber-700"><AlertTriangle className="h-4 w-4" /><span className="text-sm font-medium">{activeItem.risk_category}</span></div>
          <p className="text-sm leading-6 text-slate-800">{activeItem.ai_finding}</p>
          <p className="mt-2 text-xs leading-5 text-slate-500">{activeItem.ai_reasoning}</p>
          <textarea disabled={readOnly} value={humanNote} onChange={(event) => setHumanNote(event.target.value)} className="mt-3 min-h-20 w-full rounded-md border border-slate-200 p-2 text-sm disabled:bg-slate-50" placeholder="填写人工复核意见" />
          <div className="mt-3 grid grid-cols-3 gap-2">
            <button disabled={readOnly || isSubmitting} onClick={() => decide('approve')} className="inline-flex items-center justify-center gap-1 rounded-md bg-green-600 px-2 py-2 text-xs text-white disabled:opacity-50"><CheckCircle className="h-3 w-3" />通过</button>
            <button disabled={readOnly || isSubmitting} onClick={() => decide('edit')} className="inline-flex items-center justify-center gap-1 rounded-md bg-blue-600 px-2 py-2 text-xs text-white disabled:opacity-50">修正</button>
            <button disabled={readOnly || isSubmitting} onClick={() => decide('reject')} className="inline-flex items-center justify-center gap-1 rounded-md bg-red-600 px-2 py-2 text-xs text-white disabled:opacity-50"><XCircle className="h-3 w-3" />误报</button>
          </div>
        </div>
      ) : null}
    </aside>
  );
}
```

This is intentionally smaller than the old `HITLReviewPage`; after it works, migrate advanced rule-config preview in a separate commit if still needed.

- [ ] **Step 2: Wire review mode into stage switcher**

Modify `WorkspaceStagePanel.tsx`:

```tsx
import { ReviewIssuePanel } from './ReviewIssuePanel';
```

Add an `onEvidencePage` prop and replace review placeholder:

```tsx
if (mode === 'review') {
  return <ReviewIssuePanel sessionId={sessionId} readOnly={readOnly} onEvidencePage={onEvidencePage} />;
}
```

- [ ] **Step 3: Pass evidence page callback from workspace page**

Modify `ReviewWorkspacePage.tsx`:

```tsx
stagePanel={
  <WorkspaceStagePanel
    mode={mode}
    sessionId={sessionId || ''}
    session={session}
    content={content}
    onStartReview={handleStartReview}
    onEvidencePage={setActivePage}
  />
}
```

- [ ] **Step 4: Route `/review` to workspace**

Modify `routes.tsx`:

```tsx
{ path: '/contracts/:id/review', Component: ReviewWorkspacePage },
```

Keep `HITLReviewPage.tsx` in the repository until browser smoke confirms parity; it can remain unused for rollback during this commit.

- [ ] **Step 5: Run frontend build**

```bash
cd frontend
npm run build
```

Expected: pass.

- [ ] **Step 6: Commit review panel**

```bash
git add frontend/src/app/reviewWorkspace/components/ReviewIssuePanel.tsx frontend/src/app/reviewWorkspace/components/WorkspaceStagePanel.tsx frontend/src/app/pages/ReviewWorkspacePage.tsx frontend/src/app/routes.tsx
git commit -m "feat: reuse workspace for manual review"
```

## Task 7: Thin Wrappers and Dead UI Path Reduction

**Files:**
- Modify: `frontend/src/app/pages/ParsedDocumentPage.tsx`
- Modify: `frontend/src/app/pages/FieldVerificationPage.tsx`
- Modify: `frontend/src/app/pages/AIScanningPage.tsx`
- Modify: `frontend/src/app/pages/HITLReviewPage.tsx`

- [ ] **Step 1: Convert legacy pages to wrappers**

For each legacy page, replace the component body with the workspace component to keep imports stable:

```tsx
import { ReviewWorkspacePage } from './ReviewWorkspacePage';

export function ParsedDocumentPage() {
  return <ReviewWorkspacePage />;
}
```

Use the same pattern for:

```tsx
export function FieldVerificationPage() {
  return <ReviewWorkspacePage />;
}

export function AIScanningPage() {
  return <ReviewWorkspacePage />;
}

export function HITLReviewPage() {
  return <ReviewWorkspacePage />;
}
```

- [ ] **Step 2: Remove now-unused imports from each wrapper file**

Each wrapper file should contain only the `ReviewWorkspacePage` import and the exported wrapper function. Do not keep old stateful code behind comments.

- [ ] **Step 3: Run build**

```bash
cd frontend
npm run build
```

Expected: pass. If a named import from a legacy page disappears, update only the file that imports it.

- [ ] **Step 4: Commit wrappers**

```bash
git add frontend/src/app/pages/ParsedDocumentPage.tsx frontend/src/app/pages/FieldVerificationPage.tsx frontend/src/app/pages/AIScanningPage.tsx frontend/src/app/pages/HITLReviewPage.tsx
git commit -m "refactor: collapse legacy review pages into workspace"
```

## Task 8: End-to-End Verification

**Files:**
- No planned code changes unless verification finds a concrete defect.

- [ ] **Step 1: Run backend targeted tests**

```bash
cd backend
uv run pytest tests/test_session_document_content.py tests/test_hitl_scan_progress.py tests/test_mineru_table_fact_service.py -q
```

Expected: pass.

- [ ] **Step 2: Compile backend**

```bash
cd backend
python -m compileall app
```

Expected: no syntax errors.

- [ ] **Step 3: Build frontend**

```bash
cd frontend
npm run build
```

Expected: pass. Existing Vite warning about dynamic/static import is acceptable if unchanged.

- [ ] **Step 4: Verify live endpoints for the known parsed session**

```bash
curl -s http://127.0.0.1:8000/api/v1/sessions/267d9e3c-322b-4828-898b-8ff1a0e00854/document-content | python -m json.tool | head -80
curl -s -I http://127.0.0.1:8000/api/v1/sessions/267d9e3c-322b-4828-898b-8ff1a0e00854/source-file | head
curl -s http://127.0.0.1:8000/api/v1/sessions/267d9e3c-322b-4828-898b-8ff1a0e00854/review-pipeline-status | python -m json.tool | head -120
```

Expected: `document-content` includes `source_pdf_url`, source file returns HTTP 200 for PDF sessions, pipeline status returns stage rows or a clear unavailable state.

- [ ] **Step 5: Browser smoke routes**

Open these routes in the local frontend:

```text
http://127.0.0.1:5173/contracts/267d9e3c-322b-4828-898b-8ff1a0e00854/document
http://127.0.0.1:5173/contracts/267d9e3c-322b-4828-898b-8ff1a0e00854/fields
http://127.0.0.1:5173/contracts/267d9e3c-322b-4828-898b-8ff1a0e00854/scanning
http://127.0.0.1:5173/contracts/267d9e3c-322b-4828-898b-8ff1a0e00854/review
```

Expected:

- `/document`: middle column shows original PDF by default and parsed evidence by toggle.
- `/fields`: right panel shows extracted fields or a truthful empty state.
- `/scanning`: right panel shows backend pipeline stages and no simulated dimension text.
- `/review`: right panel shows generated review items or a truthful empty state.

- [ ] **Step 6: Final git safety check**

```bash
git status --short
git diff --check
```

Expected: `backend/contract_review.db` is not staged. All committed changes are source, tests, or docs.

## Self-Review

- Spec coverage: the plan maps the design to one shared workspace, original PDF default, parsed evidence fallback, mode-specific right panel, aborted read-only behavior, real scanning status, and wrapper cleanup.
- Backend scope: the plan avoids touching MinerU worker, water-review pipeline, and runtime DB unless a targeted test exposes a real backend contract gap.
- Frontend test reality: the project has `build` and `dev` scripts but no frontend test runner, so the plan uses `npm run build` plus browser smoke instead of inventing a new test dependency.
- Type consistency: `ReviewWorkspaceMode`, `ViewerMode`, `SessionResponse`, `ReviewDocumentContentResponse`, `ReviewPipelineStatusResponse`, and `ReviewItem` names match current `frontend/src/app/api/sessions.ts` and `frontend/src/app/types.ts`.
- Risk intentionally deferred: precise PDF bbox overlay and advanced rule-config editing are excluded from this version because they require separate coordinate and UX validation.
