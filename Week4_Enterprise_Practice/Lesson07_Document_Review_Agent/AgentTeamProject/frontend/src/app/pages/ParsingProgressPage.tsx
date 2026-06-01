import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  FileSearch,
  Loader2,
  RotateCcw,
  ScanLine,
  ShieldAlert,
  UploadCloud,
  Wifi,
  WifiOff,
  Workflow,
  XCircle,
} from 'lucide-react';
import { GlobalNav } from '../components/GlobalNav';
import { WorkflowStatusBar } from '../components/WorkflowStatusBar';
import { subscribeSSE } from '../api/sse';
import {
  abortSession,
  getLangExtractFacts,
  getReviewDocumentContent,
  getReviewPipelineStatus,
  getSession,
  retryParse,
  startReview,
} from '../api/sessions';
import type { LangExtractFactsResponse, ReviewDocumentContentResponse, ReviewPipelineStatusResponse, ReviewPipelineStage } from '../api/sessions';
import type { SessionState } from '../types';

type ParseStatus = 'parsing' | 'parsed' | 'failed' | 'timeout' | 'system_failure' | 'aborted' | 'completed';
type ParseStage =
  | 'queued'
  | 'upload_url_requested'
  | 'polling'
  | 'downloading'
  | 'completed';

const STAGES: Array<{
  id: ParseStage;
  title: string;
  description: string;
}> = [
  { id: 'queued', title: '等待解析', description: '任务已入队，等待 worker 领取' },
  { id: 'upload_url_requested', title: '上传到 MinerU', description: '获取上传地址并提交原始文件' },
  { id: 'polling', title: 'MinerU 解析中', description: '等待远端返回结构化结果' },
  { id: 'downloading', title: '获取解析结果', description: '下载并校验 MinerU 结果包' },
  { id: 'completed', title: '解析完成', description: '已保留结构化结果，尚未执行向量和审查' },
];

const STAGE_INDEX = new Map(STAGES.map((stage, index) => [stage.id, index]));

function normalizeStage(value: unknown): ParseStage {
  if (value === 'uploaded') return 'upload_url_requested';
  if (value === 'extracted' || value === 'pipeline_running') return 'completed';
  return STAGE_INDEX.has(value as ParseStage) ? (value as ParseStage) : 'queued';
}

function formatElapsed(seconds: number) {
  const min = Math.floor(seconds / 60);
  const sec = seconds % 60;
  if (min === 0) return `${sec} 秒`;
  return `${min} 分 ${String(sec).padStart(2, '0')} 秒`;
}

function errorTitle(status: ParseStatus) {
  if (status === 'aborted') return '解析已中止';
  if (status === 'timeout') return '解析超时';
  if (status === 'system_failure') return '后处理失败';
  return '解析失败';
}

function errorHint(status: ParseStatus, errorCode: string) {
  if (status === 'aborted') return '本次解析流程已经终止。可以在本页重新入队解析，不需要再次上传同一个文件。';
  if (errorCode === 'PARSE_RETRY_EXHAUSTED') return '解析重试次数已达上限，需要重新上传文件或联系管理员处理。';
  if (errorCode === 'SOURCE_FILE_MISSING') return '原始文件已不存在，无法复用当前任务重新解析，需要重新上传。';
  if (status === 'timeout') return '远端解析等待超时。可以重试，或改为上传已解析的 MinerU JSON。';
  if (status === 'system_failure') return '文件解析已返回，但字段抽取、审查流水线或向量检索阶段失败。';
  if (errorCode === 'MINERU_TOKEN_MISSING') return '后端缺少 MINERU_TOKEN，重试不会生效，需要先补齐配置。';
  if (errorCode === 'MINERU_AUTH_FAILED') return 'MinerU Token 无效或已过期，需要检查生产配置。';
  if (errorCode === 'MINERU_RATE_LIMITED') return 'MinerU 当前限流，可以稍后重试。';
  return '请检查文件是否符合 PDF / DOCX / MinerU JSON 要求，或直接上传 MinerU JSON。';
}

function stageLabel(stage: ReviewPipelineStage) {
  if (stage.status === 'cached') return '已复用缓存';
  if (stage.status === 'completed') return '已完成';
  if (stage.status === 'running') return '正在执行';
  if (stage.status === 'failed') return '失败';
  return '未开始';
}

function stageTone(stage: ReviewPipelineStage) {
  if (stage.status === 'cached') return 'border-emerald-200 bg-emerald-50 text-emerald-700';
  if (stage.status === 'completed') return 'border-blue-200 bg-blue-50 text-blue-700';
  if (stage.status === 'running') return 'border-amber-200 bg-amber-50 text-amber-700';
  if (stage.status === 'failed') return 'border-red-200 bg-red-50 text-red-700';
  return 'border-slate-200 bg-slate-50 text-slate-500';
}

function formatDurationMs(duration: number | null) {
  if (duration === null || duration === undefined) return '';
  if (duration < 1000) return `${duration} ms`;
  return `${(duration / 1000).toFixed(duration < 10_000 ? 1 : 0)} 秒`;
}

function ReviewPipelineStatusPanel({
  status,
  error,
  onRefresh,
  isRunning,
}: {
  status: ReviewPipelineStatusResponse | null;
  error: string;
  onRefresh: () => void;
  isRunning: boolean;
}) {
  const stages = status?.stages.filter((stage) => stage.id !== 'review_items_db') ?? [];
  return (
    <div className="mt-5 rounded-md border border-slate-200 bg-white">
      <div className="flex flex-col gap-2 border-b border-slate-200 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-950">数据清洗与审查缓存</h3>
          <p className="mt-0.5 text-xs text-slate-500">这里展示下一步真实产物；再次执行会优先复用已完成的缓存文件。</p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          className="inline-flex h-9 items-center justify-center rounded-md border border-slate-300 bg-white px-3 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
        >
          刷新状态
        </button>
      </div>
      <div className="p-4">
        {error ? (
          <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">{error}</div>
        ) : stages.length === 0 ? (
          <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">尚未开始数据清洗与向量审查。</div>
        ) : (
          <div className="space-y-2">
            {stages.map((stage) => (
              <div key={stage.id} className="flex flex-col gap-2 rounded-md border border-slate-100 bg-slate-50 px-3 py-2 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-medium text-slate-900">{stage.title}</p>
                    <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${stageTone(stage)}`}>
                      {stage.status === 'running' && isRunning ? '正在执行' : stageLabel(stage)}
                    </span>
                  </div>
                  <p className="mt-1 break-all text-xs text-slate-500">
                    {stage.artifact ? stage.artifact : '数据库写入'}
                    {stage.artifact_exists ? ' · 已落盘' : ''}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-3 text-xs text-slate-500">
                  {stage.item_count !== null && stage.item_count !== undefined ? <span>{stage.item_count} 条</span> : null}
                  {stage.duration_ms !== null && stage.duration_ms !== undefined ? <span>{formatDurationMs(stage.duration_ms)}</span> : null}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * ParsingProgressPage — P05 解析进度页
 * GET /sessions/{session_id} — 已开发
 * GET /sessions/{session_id}/events (SSE) — 已开发
 * POST /sessions/{session_id}/retry-parse — 已开发（最多 3 次）
 * POST /sessions/{session_id}/abort — 已开发
 */
export function ParsingProgressPage() {
  const { id: sessionId } = useParams();
  const navigate = useNavigate();
  const [sessionState, setSessionState] = useState<SessionState>('parsing');
  const [parseStatus, setParseStatus] = useState<ParseStatus>('parsing');
  const [stage, setStage] = useState<ParseStage>('queued');
  const [retryCount, setRetryCount] = useState(0);
  const [maxRetries, setMaxRetries] = useState(3);
  const [canRetryParse, setCanRetryParse] = useState(true);
  const [retryBlockReason, setRetryBlockReason] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [isScannedDocument, setIsScannedDocument] = useState(false);
  const [isAborting, setIsAborting] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const [isStartingReview, setIsStartingReview] = useState(false);
  const [startReviewError, setStartReviewError] = useState('');
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [reviewElapsedSeconds, setReviewElapsedSeconds] = useState(0);
  const [sseConnected, setSseConnected] = useState(false);
  const [documentContent, setDocumentContent] = useState<ReviewDocumentContentResponse | null>(null);
  const [documentContentError, setDocumentContentError] = useState('');
  const [langExtractFacts, setLangExtractFacts] = useState<LangExtractFactsResponse | null>(null);
  const [langExtractFactsError, setLangExtractFactsError] = useState('');
  const [reviewPipelineStatus, setReviewPipelineStatus] = useState<ReviewPipelineStatusResponse | null>(null);
  const [reviewPipelineStatusError, setReviewPipelineStatusError] = useState('');

  const currentStageIndex = STAGE_INDEX.get(stage) ?? 0;
  const progressPercent = useMemo(() => {
    if (parseStatus !== 'parsing') return 100;
    return Math.max(8, Math.round(((currentStageIndex + 1) / STAGES.length) * 100));
  }, [currentStageIndex, parseStatus]);

  const loadParsedContent = useCallback(async () => {
    if (!sessionId) return;
    try {
      const content = await getReviewDocumentContent(sessionId);
      setDocumentContent(content);
      setDocumentContentError('');
    } catch (err: any) {
      setDocumentContent(null);
      setDocumentContentError(err.message || '解析结果读取失败');
    }
  }, [sessionId]);

  const loadLangExtractFacts = useCallback(async () => {
    if (!sessionId) return;
    try {
      const facts = await getLangExtractFacts(sessionId);
      setLangExtractFacts(facts);
      setLangExtractFactsError('');
    } catch (err: any) {
      setLangExtractFacts(null);
      setLangExtractFactsError(err.message || 'LangExtract 证据事实读取失败');
    }
  }, [sessionId]);

  const loadReviewPipelineStatus = useCallback(async () => {
    if (!sessionId) return;
    try {
      const status = await getReviewPipelineStatus(sessionId);
      setReviewPipelineStatus(status);
      setReviewPipelineStatusError('');
    } catch (err: any) {
      setReviewPipelineStatus(null);
      setReviewPipelineStatusError(err.message || '数据清洗与审查状态读取失败');
    }
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    getSession(sessionId)
      .then((session) => {
        setSessionState(session.state);
        setIsScannedDocument(session.is_scanned_document);
        setRetryCount(session.retry_count ?? 0);
        setMaxRetries(session.max_retries ?? 3);
        setCanRetryParse(session.can_retry_parse ?? true);
        setRetryBlockReason(session.retry_block_reason ?? null);
        if (session.latest_parse_job_stage) setStage(normalizeStage(session.latest_parse_job_stage));
        if (session.state === 'parsed') {
          setParseStatus('parsed');
          setStage('completed');
          void loadParsedContent();
          void loadLangExtractFacts();
          void loadReviewPipelineStatus();
          return;
        }
        if (session.state === 'aborted') {
          setParseStatus('aborted');
          setErrorCode(session.latest_parse_job_error_code || session.retry_block_reason || 'USER_ABORTED');
          setErrorMessage(session.latest_parse_job_error_message || '本次解析已中止');
          return;
        }
        if (session.state === 'scanning' || session.state === 'hitl_pending') {
          navigate(`/contracts/${sessionId}/fields`);
        }
      })
      .catch(() => {});
  }, [sessionId, navigate, loadParsedContent, loadLangExtractFacts, loadReviewPipelineStatus]);

  useEffect(() => {
    if (!sessionId || parseStatus !== 'parsing') return;

    const unsubscribe = subscribeSSE(sessionId, (event, data) => {
      if (event === 'connected') {
        setSseConnected(true);
        return;
      }

      if (event === 'parse_started' || event === 'parse_progress') {
        setSessionState('parsing');
        setCanRetryParse(false);
        setRetryBlockReason(null);
        setStage(normalizeStage(data.stage));
        if (typeof data.retry_count === 'number') setRetryCount(data.retry_count);
        if (typeof data.max_retries === 'number') setMaxRetries(data.max_retries);
        return;
      }

      if (event === 'session_aborted') {
        setSessionState('aborted');
        setParseStatus('aborted');
        setCanRetryParse(false);
        setRetryBlockReason('USER_ABORTED');
        setErrorCode('USER_ABORTED');
        setErrorMessage(String(data.reason || '本次解析已中止'));
        return;
      }

      if (event === 'state_changed') {
        const newState = (data as any).state || (data as any).new_state;
        if (newState) setSessionState(newState);
        if (newState === 'aborted') {
          setParseStatus('aborted');
          setCanRetryParse(false);
          setRetryBlockReason('USER_ABORTED');
          setErrorCode('USER_ABORTED');
          setErrorMessage('本次解析已中止');
          return;
        }
        if (newState === 'parsed') {
          setParseStatus('parsed');
          setCanRetryParse(false);
          setRetryBlockReason('PARSE_ALREADY_SUCCEEDED');
          setStage('completed');
          void loadParsedContent();
          void loadLangExtractFacts();
          void loadReviewPipelineStatus();
          return;
        }
        if (newState === 'scanning' || newState === 'hitl_pending') {
          navigate(`/contracts/${sessionId}/fields`);
        }
        return;
      }

      if (event === 'parse_failed' || event === 'parse_timeout' || event === 'system_failure') {
        setParseStatus(event === 'parse_timeout' ? 'timeout' : event === 'system_failure' ? 'system_failure' : 'failed');
        setRetryCount(typeof data.retry_count === 'number' ? data.retry_count : retryCount);
        setMaxRetries(typeof data.max_retries === 'number' ? data.max_retries : maxRetries);
        const nextRetryCount = typeof data.retry_count === 'number' ? data.retry_count : retryCount;
        const nextMaxRetries = typeof data.max_retries === 'number' ? data.max_retries : maxRetries;
        setCanRetryParse(nextRetryCount < nextMaxRetries);
        setRetryBlockReason(nextRetryCount >= nextMaxRetries ? 'PARSE_RETRY_EXHAUSTED' : null);
        setErrorCode(String(data.error_code || ''));
        setErrorMessage(String(data.message || ''));
      }
    });

    return unsubscribe;
  }, [sessionId, parseStatus, navigate, retryCount, maxRetries, loadParsedContent, loadLangExtractFacts, loadReviewPipelineStatus]);

  useEffect(() => {
    if (parseStatus !== 'parsing') return;
    const tick = setInterval(() => setElapsedSeconds((s) => s + 1), 1000);
    return () => clearInterval(tick);
  }, [parseStatus]);

  useEffect(() => {
    if (!isStartingReview) return;
    const tick = setInterval(() => setReviewElapsedSeconds((s) => s + 1), 1000);
    return () => clearInterval(tick);
  }, [isStartingReview]);

  useEffect(() => {
    if (!isStartingReview) return;
    void loadReviewPipelineStatus();
    const tick = setInterval(() => {
      void loadReviewPipelineStatus();
    }, 2500);
    return () => clearInterval(tick);
  }, [isStartingReview, loadReviewPipelineStatus]);

  const handleRetry = async () => {
    if (!canRetryParse || retryCount >= maxRetries || !sessionId) return;
    setIsRetrying(true);
    try {
      const result = await retryParse(sessionId);
      setSessionState('parsing');
      setCanRetryParse(false);
      setRetryBlockReason(null);
      setRetryCount(result.retry_count);
      setMaxRetries(result.max_retries);
      setParseStatus('parsing');
      setStage('queued');
      setElapsedSeconds(0);
      setErrorCode('');
      setErrorMessage('');
      setDocumentContent(null);
      setLangExtractFacts(null);
      setReviewPipelineStatus(null);
      setDocumentContentError('');
      setLangExtractFactsError('');
      setReviewPipelineStatusError('');
      setStartReviewError('');
    } catch (err: any) {
      setErrorCode('RETRY_REQUEST_FAILED');
      setErrorMessage(err.message || '重试失败');
      setParseStatus('failed');
    } finally {
      setIsRetrying(false);
    }
  };

  const handleStartReview = async () => {
    if (!sessionId || parseStatus !== 'parsed') return;
    setIsStartingReview(true);
    setReviewElapsedSeconds(0);
    setStartReviewError('');
    void loadReviewPipelineStatus();
    try {
      const result = await startReview(sessionId);
      setSessionState(result.state as SessionState);
      navigate(`/contracts/${sessionId}/fields`);
    } catch (err: any) {
      setStartReviewError(err.message || '数据清洗与向量审查失败，MinerU 解析结果已保留');
      await loadParsedContent();
      await loadLangExtractFacts();
      await loadReviewPipelineStatus();
    } finally {
      setIsStartingReview(false);
    }
  };

  const handleAbort = async () => {
    if (!sessionId) return;
    if (!window.confirm('确定要放弃本次评审流程吗？此操作不可逆。')) return;
    setIsAborting(true);
    try {
      await abortSession(sessionId, '用户主动放弃');
      navigate('/contracts');
    } catch (err: any) {
      setErrorCode('ABORT_REQUEST_FAILED');
      setErrorMessage(err.message || '放弃失败');
      setParseStatus('failed');
      setIsAborting(false);
    }
  };

  const activeStage = STAGES[currentStageIndex] ?? STAGES[0];
  const retryRemaining = Math.max(0, maxRetries - retryCount);
  const retryDisabled = !canRetryParse || retryRemaining <= 0 || isRetrying;
  const parsedBlockCount = documentContent?.pages.reduce((total, page) => total + page.blocks.length, 0) ?? 0;
  const previewBlocks = documentContent?.pages.flatMap((page) => page.blocks.slice(0, 4)).slice(0, 8) ?? [];
  const factPreview = langExtractFacts?.facts.slice(0, 8) ?? [];
  const topFieldCounts = Object.entries(langExtractFacts?.field_counts ?? {}).slice(0, 8);

  return (
    <div className="min-h-screen bg-slate-50">
      <GlobalNav />
      <WorkflowStatusBar sessionState={sessionState} />
      <main className="pt-[118px]">
        <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6 lg:px-8">
          <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h1 className="text-xl font-semibold text-slate-950">解析方案文件</h1>
              <p className="mt-1 text-sm text-slate-600">先完成 MinerU 文件解析；字段、向量和规则审查在下一步执行。</p>
            </div>
            <div
              className={`inline-flex h-9 w-fit items-center gap-2 rounded-full border px-3 text-sm ${
                sseConnected
                  ? 'border-green-200 bg-green-50 text-green-700'
                  : 'border-slate-200 bg-white text-slate-500'
              }`}
            >
              {sseConnected ? <Wifi className="h-4 w-4" /> : <WifiOff className="h-4 w-4" />}
              {sseConnected ? '实时状态已连接' : '正在连接实时状态'}
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
            <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm" aria-live="polite">
              {parseStatus === 'parsing' ? (
                <div>
                  <div className="flex items-start gap-4">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-blue-100 text-blue-700">
                      <Loader2 className="h-6 w-6 animate-spin" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-blue-700">当前步骤</p>
                      <h2 className="mt-1 text-lg font-semibold text-slate-950">{activeStage.title}</h2>
                      <p className="mt-1 text-sm text-slate-600">{activeStage.description}</p>
                    </div>
                  </div>

                  <div className="mt-6">
                    <div className="mb-2 flex items-center justify-between text-xs text-slate-500">
                      <span>{progressPercent}%</span>
                      <span>已用时 {formatElapsed(elapsedSeconds)}</span>
                    </div>
                    <div
                      className="h-2 overflow-hidden rounded-full bg-slate-200"
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={progressPercent}
                    >
                      <div
                        className="h-full rounded-full bg-blue-600 transition-[width] duration-300"
                        style={{ width: `${progressPercent}%` }}
                      />
                    </div>
                  </div>

                  <ol className="mt-6 space-y-3">
                    {STAGES.map((item, index) => {
                      const complete = index < currentStageIndex;
                      const active = index === currentStageIndex;
                      return (
                        <li key={item.id} className="flex gap-3">
                          <div
                            className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border ${
                              complete
                                ? 'border-blue-600 bg-blue-600 text-white'
                                : active
                                  ? 'border-blue-600 bg-blue-50 text-blue-700'
                                  : 'border-slate-300 bg-white text-slate-400'
                            }`}
                          >
                            {complete ? <CheckCircle2 className="h-4 w-4" /> : active ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <span className="h-1.5 w-1.5 rounded-full bg-current" />}
                          </div>
                          <div>
                            <p className={`text-sm font-medium ${active ? 'text-slate-950' : 'text-slate-700'}`}>
                              {item.title}
                            </p>
                            <p className="text-xs text-slate-500">{item.description}</p>
                          </div>
                        </li>
                      );
                    })}
                  </ol>

                  {isScannedDocument && (
                    <div className="mt-6 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                      <div className="flex gap-2">
                        <ScanLine className="mt-0.5 h-4 w-4 shrink-0" />
                        <div>
                          <p className="font-medium">扫描件精度提示</p>
                          <p className="mt-0.5 text-amber-700">
                            OCR 结果可能受扫描质量影响，后续字段核对阶段需要重点检查项目名称、面积、投资和土石方数据。
                          </p>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              ) : parseStatus === 'parsed' ? (
                <div>
                  <div className="flex items-start gap-4">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-700">
                      <CheckCircle2 className="h-6 w-6" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-emerald-700">MinerU 解析完成</p>
                      <h2 className="mt-1 text-lg font-semibold text-slate-950">已生成结构化解析结果</h2>
                      <p className="mt-1 text-sm text-slate-600">
                        当前只完成文件解析。字段抽取、向量检索和规则审查需要手动进入下一步。
                      </p>
                    </div>
                  </div>

                  <div className="mt-5 grid gap-3 sm:grid-cols-3">
                    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                      <p className="text-xs text-slate-500">页数</p>
                      <p className="mt-1 text-lg font-semibold text-slate-950">{documentContent?.page_count ?? '-'}</p>
                    </div>
                    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                      <p className="text-xs text-slate-500">解析块</p>
                      <p className="mt-1 text-lg font-semibold text-slate-950">{parsedBlockCount || '-'}</p>
                    </div>
                    <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                      <p className="text-xs text-slate-500">来源</p>
                      <p className="mt-1 text-sm font-medium text-slate-950">{documentContent?.source || 'MinerU'}</p>
                    </div>
                  </div>

                  <ReviewPipelineStatusPanel
                    status={reviewPipelineStatus}
                    error={reviewPipelineStatusError}
                    onRefresh={loadReviewPipelineStatus}
                    isRunning={isStartingReview}
                  />

                  {documentContentError ? (
                    <div className="mt-5 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                      {documentContentError}
                    </div>
                  ) : (
                    <div className="mt-5 rounded-md border border-slate-200">
                      <div className="border-b border-slate-200 px-4 py-3">
                        <h3 className="text-sm font-semibold text-slate-950">解析内容预览</h3>
                      </div>
                      <div className="max-h-80 overflow-auto p-4">
                        {previewBlocks.length === 0 ? (
                          <p className="text-sm text-slate-500">暂无可预览文本块。</p>
                        ) : (
                          <div className="space-y-3">
                            {previewBlocks.map((block) => (
                              <div key={block.block_id} className="rounded-md border border-slate-100 bg-white p-3">
                                <div className="mb-1 flex items-center gap-2 text-xs text-slate-400">
                                  <span>第 {block.page} 页</span>
                                  <span>{block.type}</span>
                                </div>
                                <p className="line-clamp-3 text-sm leading-6 text-slate-700">{block.text || block.image_path || '-'}</p>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  <div className="mt-5 rounded-md border border-slate-200">
                    <div className="flex flex-col gap-2 border-b border-slate-200 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-950">LangExtract 证据事实库</h3>
                        <p className="mt-0.5 text-xs text-slate-500">字段抽取、公式核验和规则审查复用这里的 fact_id、chunk_id、页码与 bbox 证据。</p>
                      </div>
                      <button
                        type="button"
                        onClick={loadLangExtractFacts}
                        className="inline-flex h-9 items-center justify-center rounded-md border border-slate-300 bg-white px-3 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                      >
                        刷新事实库
                      </button>
                    </div>
                    <div className="p-4">
                      {langExtractFactsError ? (
                        <div className="rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                          {langExtractFactsError}
                        </div>
                      ) : !langExtractFacts?.available ? (
                        <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm text-slate-600">
                          {langExtractFacts?.message || '尚未生成。点击“开始数据清洗与向量审查”后，会先生成并保存这一份事实库。'}
                        </div>
                      ) : (
                        <div className="space-y-4">
                          <div className="grid gap-3 sm:grid-cols-3">
                            <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                              <p className="text-xs text-slate-500">事实数</p>
                              <p className="mt-1 text-lg font-semibold text-slate-950">{langExtractFacts.fact_count}</p>
                            </div>
                            <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                              <p className="text-xs text-slate-500">字段种类</p>
                              <p className="mt-1 text-lg font-semibold text-slate-950">{Object.keys(langExtractFacts.field_counts).length}</p>
                            </div>
                            <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
                              <p className="text-xs text-slate-500">跨章节线索</p>
                              <p className="mt-1 text-lg font-semibold text-slate-950">{langExtractFacts.finding_count}</p>
                            </div>
                          </div>

                          {topFieldCounts.length > 0 && (
                            <div className="flex flex-wrap gap-2">
                              {topFieldCounts.map(([field, count]) => (
                                <span key={field} className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700">
                                  {field} × {count}
                                </span>
                              ))}
                            </div>
                          )}

                          <div className="max-h-80 overflow-auto space-y-3">
                            {factPreview.map((fact, index) => {
                              const pageRange = Array.isArray(fact.page_range) && fact.page_range.length > 0 ? fact.page_range.join('-') : '-';
                              return (
                                <div key={fact.fact_id || `${fact.field_name}-${index}`} className="rounded-md border border-slate-100 bg-white p-3">
                                  <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-400">
                                    <span>{fact.field_name || 'unknown_field'}</span>
                                    <span>第 {pageRange} 页</span>
                                    <span>{fact.confidence ?? '-'}%</span>
                                  </div>
                                  <p className="text-sm font-medium leading-6 text-slate-900">
                                    {fact.value || fact.normalized_value || '-'}
                                    {fact.unit ? <span className="ml-1 text-slate-500">{fact.unit}</span> : null}
                                  </p>
                                  {fact.source_text && (
                                    <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-500">{fact.source_text}</p>
                                  )}
                                  <p className="mt-2 text-xs text-slate-400">
                                    {fact.fact_id || '-'} · {fact.chunk_id || '-'}
                                  </p>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  {startReviewError && (
                    <div className="mt-5 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                      {startReviewError}
                    </div>
                  )}

                  <div className="mt-5 flex flex-col gap-3 sm:flex-row">
                    <button
                      type="button"
                      onClick={handleStartReview}
                      disabled={isStartingReview}
                      className="inline-flex h-11 items-center justify-center gap-2 rounded-md bg-blue-600 px-4 text-sm font-medium text-white transition-colors hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:bg-slate-300"
                    >
                      {isStartingReview ? <Loader2 className="h-4 w-4 animate-spin" /> : <Workflow className="h-4 w-4" />}
                      {isStartingReview ? '正在执行清洗与审查' : '开始数据清洗与向量审查'}
                    </button>
                    <button
                      type="button"
                      onClick={loadParsedContent}
                      className="inline-flex h-11 items-center justify-center rounded-md border border-slate-300 bg-white px-4 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                    >
                      刷新解析结果
                    </button>
                  </div>
                  {isStartingReview && (
                    <div className="mt-3 rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-800">
                      已用时 {formatElapsed(reviewElapsedSeconds)}。下方缓存列表会显示真实已落盘产物；如果某一步已经完成，再次进入会优先复用对应文件。
                    </div>
                  )}
                </div>
              ) : (
                <div role="alert" aria-live="assertive">
                  <div className="flex items-start gap-4">
                    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-red-100 text-red-700">
                      {parseStatus === 'system_failure' ? <ShieldAlert className="h-6 w-6" /> : parseStatus === 'aborted' ? <XCircle className="h-6 w-6" /> : <AlertTriangle className="h-6 w-6" />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-red-700">{errorTitle(parseStatus)}</p>
                      <h2 className="mt-1 text-lg font-semibold text-slate-950">
                        {errorMessage || errorHint(parseStatus, errorCode)}
                      </h2>
                      <p className="mt-2 text-sm text-slate-600">{errorHint(parseStatus, errorCode)}</p>
                    </div>
                  </div>

                  <div className="mt-5 rounded-md border border-slate-200 bg-slate-50 p-3">
                    <dl className="grid gap-3 text-sm sm:grid-cols-3">
                      <div>
                        <dt className="text-xs text-slate-500">错误码</dt>
                        <dd className="mt-1 break-words font-medium text-slate-900">{errorCode || '-'}</dd>
                      </div>
                      <div>
                        <dt className="text-xs text-slate-500">重试次数</dt>
                        <dd className="mt-1 font-medium text-slate-900">{retryCount}/{maxRetries}</dd>
                      </div>
                      <div>
                        <dt className="text-xs text-slate-500">已用时</dt>
                        <dd className="mt-1 font-medium text-slate-900">{formatElapsed(elapsedSeconds)}</dd>
                      </div>
                    </dl>
                  </div>

                  <div className="mt-5 flex flex-col gap-3 sm:flex-row">
                    <button
                      type="button"
                      onClick={handleRetry}
                      disabled={retryDisabled}
                      className="inline-flex h-11 items-center justify-center gap-2 rounded-md bg-blue-600 px-4 text-sm font-medium text-white transition-colors hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:bg-slate-300"
                    >
                      <RotateCcw className={`h-4 w-4 ${isRetrying ? 'animate-spin' : ''}`} />
                      {!canRetryParse ? '不可重新解析' : retryRemaining <= 0 ? '已达最大重试次数' : `重新解析，剩余 ${retryRemaining} 次`}
                    </button>
                    <button
                      type="button"
                      onClick={() => navigate('/contracts/upload')}
                      className="inline-flex h-11 items-center justify-center rounded-md border border-slate-300 bg-white px-4 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                    >
                      重新上传文件
                    </button>
                  </div>
                </div>
              )}
            </section>

            <aside className="space-y-4">
              <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <h2 className="text-sm font-semibold text-slate-950">解析策略</h2>
                <div className="mt-4 space-y-3">
                  <div className="flex gap-2">
                    <UploadCloud className="mt-0.5 h-4 w-4 shrink-0 text-blue-600" />
                    <div>
                      <p className="text-sm font-medium text-slate-800">PDF / DOCX</p>
                      <p className="text-xs text-slate-500">先经 MinerU 生成结构化结果，不自动执行审查。</p>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <FileSearch className="mt-0.5 h-4 w-4 shrink-0 text-blue-600" />
                    <div>
                      <p className="text-sm font-medium text-slate-800">MinerU JSON</p>
                      <p className="text-xs text-slate-500">作为已解析结果导入，随后可手动进入下一步。</p>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Workflow className="mt-0.5 h-4 w-4 shrink-0 text-blue-600" />
                    <div>
                      <p className="text-sm font-medium text-slate-800">失败边界</p>
                      <p className="text-xs text-slate-500">MinerU 失败只影响解析；后续 pipeline 失败不覆盖解析结果。</p>
                    </div>
                  </div>
                </div>
              </section>

              <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <h2 className="text-sm font-semibold text-slate-950">操作</h2>
                <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
                  <Clock3 className="mr-1 inline h-3.5 w-3.5 align-[-2px]" />
                  解析完成后会停留在本页展示结果，再由你决定是否进入数据清洗与向量审查。
                </div>
                {parseStatus === 'aborted' ? (
                  <button
                    type="button"
                    onClick={() => navigate('/contracts')}
                    className="mt-3 inline-flex h-11 w-full items-center justify-center rounded-md border border-slate-300 bg-white px-4 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                  >
                    返回方案列表
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={handleAbort}
                    disabled={isAborting}
                    className="mt-3 inline-flex h-11 w-full items-center justify-center gap-2 rounded-md border border-red-200 bg-white px-4 text-sm font-medium text-red-700 transition-colors hover:bg-red-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <XCircle className="h-4 w-4" />
                    {isAborting ? '正在放弃' : '放弃并返回列表'}
                  </button>
                )}
              </section>
            </aside>
          </div>
        </div>
      </main>
    </div>
  );
}
