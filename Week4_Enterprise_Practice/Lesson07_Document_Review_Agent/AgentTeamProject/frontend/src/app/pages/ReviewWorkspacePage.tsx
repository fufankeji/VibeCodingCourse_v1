import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router';
import { ArrowLeft, Loader2 } from 'lucide-react';
import {
  getReviewDocumentContent,
  getSession,
  startReview,
  type ReviewDocumentContentResponse,
  type SessionResponse,
} from '../api/sessions';
import { DocumentNavigator } from '../reviewWorkspace/components/DocumentNavigator';
import { DocumentViewer } from '../reviewWorkspace/components/DocumentViewer';
import { ReviewWorkspaceShell } from '../reviewWorkspace/components/ReviewWorkspaceShell';
import { WorkspaceStagePanel } from '../reviewWorkspace/components/WorkspaceStagePanel';
import { findPage, firstPageNumber } from '../reviewWorkspace/document';
import { isReadOnlySession, modeDescription, modeFromPath, modeTitle } from '../reviewWorkspace/mode';
import type { ReviewWorkspaceMode, ViewerMode } from '../reviewWorkspace/types';
import type { SessionState } from '../types';

const MODE_LINKS: Array<{ mode: ReviewWorkspaceMode; label: string; path: string }> = [
  { mode: 'document', label: '解析文档', path: 'document' },
  { mode: 'fields', label: '关键信息', path: 'fields' },
  { mode: 'scanning', label: '清洗审查', path: 'scanning' },
  { mode: 'review', label: '人工复核', path: 'review' },
];

export function ReviewWorkspacePage() {
  const { id: sessionId = '' } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const mode = modeFromPath(location.pathname);
  const [session, setSession] = useState<SessionResponse | null>(null);
  const [content, setContent] = useState<ReviewDocumentContentResponse | null>(null);
  const [activePageNumber, setActivePageNumber] = useState(1);
  const [viewerMode, setViewerMode] = useState<ViewerMode>('pdf');
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [isStartingReview, setIsStartingReview] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    let canceled = false;
    setIsLoading(true);
    setLoadError('');

    Promise.allSettled([getSession(sessionId), getReviewDocumentContent(sessionId)])
      .then(([sessionResult, contentResult]) => {
        if (canceled) return;
        if (sessionResult.status === 'fulfilled') {
          setSession(sessionResult.value);
        }
        if (contentResult.status === 'fulfilled') {
          setContent(contentResult.value);
          setActivePageNumber(firstPageNumber(contentResult.value));
          setViewerMode(contentResult.value.source_pdf_url ? 'pdf' : 'parsed');
        } else {
          setContent(null);
          setViewerMode('parsed');
          setLoadError(contentResult.reason?.message || '解析文档读取失败');
        }
      })
      .finally(() => {
        if (!canceled) setIsLoading(false);
      });

    return () => {
      canceled = true;
    };
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    let canceled = false;
    getSession(sessionId)
      .then((res) => {
        if (!canceled) setSession(res);
      })
      .catch(() => {});
    return () => {
      canceled = true;
    };
  }, [sessionId, location.pathname]);

  const activePage = useMemo(() => findPage(content, activePageNumber), [content, activePageNumber]);
  const sessionState = (session?.state || 'parsed') as SessionState;
  const readOnly = isReadOnlySession(session);

  const handleStartReview = async () => {
    if (!sessionId || readOnly || isStartingReview) return;
    setIsStartingReview(true);
    try {
      await startReview(sessionId);
      setSession((current) => (current ? { ...current, state: 'scanning' } : current));
      navigate(`/contracts/${sessionId}/scanning`);
    } finally {
      setIsStartingReview(false);
    }
  };

  const header = (
    <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <button
          type="button"
          onClick={() => navigate('/contracts')}
          className="mb-3 inline-flex items-center gap-2 text-sm text-slate-500 hover:text-slate-800"
        >
          <ArrowLeft className="h-4 w-4" />
          返回方案列表
        </button>
        <h1 className="text-xl font-semibold text-slate-950">{modeTitle(mode)}</h1>
        <p className="mt-1 text-sm text-slate-600">{modeDescription(mode)}</p>
        {readOnly ? (
          <p className="mt-2 rounded-md border border-slate-200 bg-slate-100 px-3 py-2 text-xs text-slate-600">
            当前会话只读：可以查看已生成数据，不能执行字段修改、重新审查或人工复核提交。
          </p>
        ) : null}
      </div>
      <ModeLinks sessionId={sessionId} mode={mode} onNavigate={navigate} />
    </div>
  );

  const navigator = isLoading ? (
    <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-500">正在加载导航</div>
  ) : (
    <DocumentNavigator
      mode={mode}
      content={content}
      activePageNumber={activePageNumber}
      onPageChange={setActivePageNumber}
    />
  );

  const viewer = isLoading ? (
    <div className="flex items-center justify-center rounded-lg border border-slate-200 bg-white py-20 text-slate-500">
      <Loader2 className="mr-2 h-5 w-5 animate-spin" />
      正在读取文档工作台
    </div>
  ) : loadError ? (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">{loadError}</div>
  ) : (
    <DocumentViewer
      content={content}
      activePage={activePage}
      activePageNumber={activePageNumber}
      viewerMode={viewerMode}
      onViewerModeChange={setViewerMode}
    />
  );

  const stagePanel = (
    <WorkspaceStagePanel
      mode={mode}
      sessionId={sessionId}
      session={session}
      content={content}
      isStartingReview={isStartingReview}
      onStartReview={handleStartReview}
      onEvidencePage={setActivePageNumber}
    />
  );

  return (
    <ReviewWorkspaceShell
      sessionState={sessionState}
      scanningStarted={mode === 'scanning' || mode === 'review' ? sessionState === 'scanning' : undefined}
      header={header}
      navigator={navigator}
      viewer={viewer}
      stagePanel={stagePanel}
    />
  );
}

function ModeLinks({
  sessionId,
  mode,
  onNavigate,
}: {
  sessionId: string;
  mode: ReviewWorkspaceMode;
  onNavigate: (path: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2 sm:justify-end">
      {MODE_LINKS.map((link) => (
        <button
          key={link.mode}
          type="button"
          onClick={() => onNavigate(`/contracts/${sessionId}/${link.path}`)}
          className={`rounded-md border px-3 py-2 text-sm transition-colors ${
            link.mode === mode
              ? 'border-slate-900 bg-slate-900 text-white'
              : 'border-slate-200 bg-white text-slate-700 hover:bg-slate-50'
          }`}
        >
          {link.label}
        </button>
      ))}
    </div>
  );
}
