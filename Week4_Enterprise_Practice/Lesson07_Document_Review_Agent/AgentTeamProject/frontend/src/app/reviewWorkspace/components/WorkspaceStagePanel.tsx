import type { ReviewDocumentContentResponse, SessionResponse } from '../../api/sessions';
import { ExtractedFieldsSummary } from '../../components/ExtractedFieldsSummary';
import type { ReviewWorkspaceMode } from '../types';
import { canStartReview, isReadOnlySession } from '../mode';
import { FieldsStagePanel } from './FieldsStagePanel';
import { ReviewIssuePanel } from './ReviewIssuePanel';
import { ScanningStagePanel } from './ScanningStagePanel';

export function WorkspaceStagePanel({
  mode,
  sessionId,
  session,
  content,
  isStartingReview = false,
  onStartReview,
  onEvidencePage,
}: {
  mode: ReviewWorkspaceMode;
  sessionId: string;
  session: SessionResponse | null;
  content: ReviewDocumentContentResponse | null;
  isStartingReview?: boolean;
  onStartReview: () => void;
  onEvidencePage: (page: number) => void;
}) {
  const readOnly = isReadOnlySession(session);

  if (mode === 'fields') return <FieldsStagePanel sessionId={sessionId} readOnly={readOnly} />;
  if (mode === 'scanning') {
    return (
      <div className="space-y-4">
        <ExtractedFieldsSummary sessionId={sessionId} dense limit={8} />
        <ScanningStagePanel sessionId={sessionId} session={session} readOnly={readOnly} />
      </div>
    );
  }
  if (mode === 'review') {
    return (
      <div className="space-y-4">
        <ExtractedFieldsSummary sessionId={sessionId} dense limit={8} />
        <ReviewIssuePanel sessionId={sessionId} readOnly={readOnly} onEvidencePage={onEvidencePage} />
      </div>
    );
  }

  return (
    <aside className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="text-base font-semibold text-slate-950">解析结果</h2>
      <div className="mt-4 space-y-2 text-sm text-slate-600">
        <p>页数：{content?.page_count ?? '-'}</p>
        <p>来源：{content?.source ?? '-'}</p>
        <p>原始 PDF：{content?.source_pdf_url ? '可查看' : '无'}</p>
      </div>
      {readOnly ? (
        <p className="mt-4 rounded-md bg-slate-50 p-2 text-xs text-slate-500">
          当前会话只读，不能启动后续审查。
        </p>
      ) : null}
      <button
        type="button"
        disabled={!canStartReview(session) || isStartingReview}
        onClick={onStartReview}
        className="mt-4 inline-flex h-10 w-full items-center justify-center rounded-md bg-slate-900 px-3 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"
      >
        {isStartingReview ? '正在启动...' : '开始清洗与规则审查'}
      </button>
    </aside>
  );
}
