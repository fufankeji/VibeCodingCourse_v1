import { useEffect, useMemo, useState } from 'react';
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
import { abortSession, getSession, retryParse } from '../api/sessions';
import type { SessionState } from '../types';

type ParseStatus = 'parsing' | 'failed' | 'timeout' | 'system_failure' | 'aborted' | 'completed';
type ParseStage =
  | 'queued'
  | 'upload_url_requested'
  | 'uploaded'
  | 'polling'
  | 'downloading'
  | 'extracted'
  | 'pipeline_running'
  | 'completed';

const STAGES: Array<{
  id: ParseStage;
  title: string;
  description: string;
}> = [
  { id: 'queued', title: '等待任务领取', description: '解析任务已进入队列' },
  { id: 'upload_url_requested', title: '准备 MinerU 上传', description: '正在获取上传地址' },
  { id: 'uploaded', title: '文件上传完成', description: '等待 MinerU 开始解析' },
  { id: 'polling', title: 'MinerU 解析中', description: '正在轮询远端解析结果' },
  { id: 'downloading', title: '下载解析结果', description: '正在获取结果包' },
  { id: 'extracted', title: '提取结构化内容', description: '已生成可审查文本与结构' },
  { id: 'pipeline_running', title: '生成审查数据', description: '正在复用字段抽取与向量检索链路' },
  { id: 'completed', title: '解析完成', description: '即将进入字段核对' },
];

const STAGE_INDEX = new Map(STAGES.map((stage, index) => [stage.id, index]));

function normalizeStage(value: unknown): ParseStage {
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
  if (status === 'timeout') return '远端解析等待超时。可以重试，或改为上传已解析的 MinerU JSON。';
  if (status === 'system_failure') return '文件解析已返回，但字段抽取、审查流水线或向量检索阶段失败。';
  if (errorCode === 'MINERU_TOKEN_MISSING') return '后端缺少 MINERU_TOKEN，重试不会生效，需要先补齐配置。';
  if (errorCode === 'MINERU_AUTH_FAILED') return 'MinerU Token 无效或已过期，需要检查生产配置。';
  if (errorCode === 'MINERU_RATE_LIMITED') return 'MinerU 当前限流，可以稍后重试。';
  return '请检查文件是否符合 PDF / DOCX / MinerU JSON 要求，或直接上传 MinerU JSON。';
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
  const [errorCode, setErrorCode] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [isScannedDocument, setIsScannedDocument] = useState(false);
  const [isAborting, setIsAborting] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [sseConnected, setSseConnected] = useState(false);

  const currentStageIndex = STAGE_INDEX.get(stage) ?? 0;
  const progressPercent = useMemo(() => {
    if (parseStatus !== 'parsing') return 100;
    return Math.max(8, Math.round(((currentStageIndex + 1) / STAGES.length) * 100));
  }, [currentStageIndex, parseStatus]);

  useEffect(() => {
    if (!sessionId) return;
    getSession(sessionId)
      .then((session) => {
        setSessionState(session.state);
        setIsScannedDocument(session.is_scanned_document);
        if (session.state === 'aborted') {
          setParseStatus('aborted');
          setErrorCode('USER_ABORTED');
          setErrorMessage('本次解析已中止');
          return;
        }
        if (session.state === 'scanning' || session.state === 'hitl_pending') {
          navigate(`/contracts/${sessionId}/fields`);
        }
      })
      .catch(() => {});
  }, [sessionId, navigate]);

  useEffect(() => {
    if (!sessionId || parseStatus !== 'parsing') return;

    const unsubscribe = subscribeSSE(sessionId, (event, data) => {
      if (event === 'connected') {
        setSseConnected(true);
        return;
      }

      if (event === 'parse_started' || event === 'parse_progress') {
        setSessionState('parsing');
        setStage(normalizeStage(data.stage));
        if (typeof data.retry_count === 'number') setRetryCount(data.retry_count);
        if (typeof data.max_retries === 'number') setMaxRetries(data.max_retries);
        return;
      }

      if (event === 'state_changed') {
        const newState = (data as any).state || (data as any).new_state;
        if (newState) setSessionState(newState);
        if (newState === 'aborted') {
          setParseStatus('aborted');
          setErrorCode('USER_ABORTED');
          setErrorMessage('本次解析已中止');
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
        setErrorCode(String(data.error_code || ''));
        setErrorMessage(String(data.message || ''));
      }
    });

    return unsubscribe;
  }, [sessionId, parseStatus, navigate, retryCount, maxRetries]);

  useEffect(() => {
    if (parseStatus !== 'parsing') return;
    const tick = setInterval(() => setElapsedSeconds((s) => s + 1), 1000);
    return () => clearInterval(tick);
  }, [parseStatus]);

  const handleRetry = async () => {
    if (retryCount >= maxRetries || !sessionId) return;
    setIsRetrying(true);
    try {
      const result = await retryParse(sessionId);
      setSessionState('parsing');
      setRetryCount(result.retry_count);
      setMaxRetries(result.max_retries);
      setParseStatus('parsing');
      setStage('queued');
      setElapsedSeconds(0);
      setErrorCode('');
      setErrorMessage('');
    } catch (err: any) {
      setErrorCode('RETRY_REQUEST_FAILED');
      setErrorMessage(err.message || '重试失败');
      setParseStatus('failed');
    } finally {
      setIsRetrying(false);
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

  return (
    <div className="min-h-screen bg-slate-50">
      <GlobalNav />
      <WorkflowStatusBar sessionState={sessionState} />
      <main className="pt-[118px]">
        <div className="mx-auto max-w-5xl px-4 py-6 sm:px-6 lg:px-8">
          <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <h1 className="text-xl font-semibold text-slate-950">解析方案文件</h1>
              <p className="mt-1 text-sm text-slate-600">系统正在创建可审查文本、字段和证据检索数据。</p>
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
                      disabled={retryRemaining <= 0 || isRetrying}
                      className="inline-flex h-11 items-center justify-center gap-2 rounded-md bg-blue-600 px-4 text-sm font-medium text-white transition-colors hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:bg-slate-300"
                    >
                      <RotateCcw className={`h-4 w-4 ${isRetrying ? 'animate-spin' : ''}`} />
                      {retryRemaining <= 0 ? '已达最大重试次数' : `重新解析，剩余 ${retryRemaining} 次`}
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
                      <p className="text-xs text-slate-500">先经 MinerU 解析，再进入审查流水线。</p>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <FileSearch className="mt-0.5 h-4 w-4 shrink-0 text-blue-600" />
                    <div>
                      <p className="text-sm font-medium text-slate-800">MinerU JSON</p>
                      <p className="text-xs text-slate-500">跳过远端解析，直接复用字段抽取与向量检索。</p>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <Workflow className="mt-0.5 h-4 w-4 shrink-0 text-blue-600" />
                    <div>
                      <p className="text-sm font-medium text-slate-800">失败边界</p>
                      <p className="text-xs text-slate-500">MinerU 失败和后处理失败会分开提示。</p>
                    </div>
                  </div>
                </div>
              </section>

              <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
                <h2 className="text-sm font-semibold text-slate-950">操作</h2>
                <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
                  <Clock3 className="mr-1 inline h-3.5 w-3.5 align-[-2px]" />
                  正常情况下无需停留在本页，解析完成会自动进入字段核对。
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
