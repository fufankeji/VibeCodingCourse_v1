import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { Loader2, AlertTriangle, RotateCcw, XCircle, ScanLine } from 'lucide-react';
import { GlobalNav } from '../components/GlobalNav';
import { WorkflowStatusBar } from '../components/WorkflowStatusBar';
import { subscribeSSE } from '../api/sse';
import { getSession } from '../api/sessions';
import { retryParse, abortSession } from '../api/sessions';

type ParseStatus = 'parsing' | 'failed' | 'timeout' | 'completed';

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
  const [parseStatus, setParseStatus] = useState<ParseStatus>('parsing');
  const [retryCount, setRetryCount] = useState(0);
  const [isScannedDocument, setIsScannedDocument] = useState(false);
  const [isAborting, setIsAborting] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [sseConnected, setSseConnected] = useState(false);

  // Fetch initial session state
  useEffect(() => {
    if (!sessionId) return;
    getSession(sessionId).then((session) => {
      setIsScannedDocument(session.is_scanned_document);
      if (session.state === 'scanning' || session.state === 'hitl_pending') {
        navigate(`/contracts/${sessionId}/fields`);
      }
    }).catch(() => {});
  }, [sessionId, navigate]);

  // SSE subscription
  useEffect(() => {
    if (!sessionId || parseStatus !== 'parsing') return;

    const unsubscribe = subscribeSSE(sessionId, (event, data) => {
      if (event === 'connected') {
        setSseConnected(true);
      } else if (event === 'state_changed') {
        const newState = (data as any).state || (data as any).new_state;
        if (newState === 'scanning' || newState === 'hitl_pending') {
          navigate(`/contracts/${sessionId}/fields`);
        }
      } else if (event === 'parse_failed') {
        setParseStatus('failed');
        setRetryCount((data as any).retry_count ?? retryCount);
      } else if (event === 'parse_timeout') {
        setParseStatus('timeout');
      }
    });

    return unsubscribe;
  }, [sessionId, parseStatus, navigate, retryCount]);

  // Elapsed timer
  useEffect(() => {
    if (parseStatus !== 'parsing') return;
    const tick = setInterval(() => setElapsedSeconds((s) => s + 1), 1000);
    return () => clearInterval(tick);
  }, [parseStatus]);

  const handleRetry = async () => {
    if (retryCount >= 3 || !sessionId) return;
    setIsRetrying(true);
    try {
      await retryParse(sessionId);
      setRetryCount((c) => c + 1);
      setParseStatus('parsing');
      setElapsedSeconds(0);
    } catch (err: any) {
      alert(err.message || '重试失败');
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
      alert(err.message || '放弃失败');
      setIsAborting(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <GlobalNav />
      <WorkflowStatusBar sessionState="parsing" />
      <div className="pt-14" style={{ paddingTop: 78 }}>
        <div className="max-w-2xl mx-auto px-6 py-12">
          <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-10">
            {/* Parsing State */}
            {parseStatus === 'parsing' && (
              <div className="text-center space-y-5">
                <div className="relative inline-flex">
                  <div className="w-16 h-16 bg-blue-50 rounded-full flex items-center justify-center">
                    <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
                  </div>
                  {isScannedDocument && (
                    <div className="absolute -top-1 -right-1 w-6 h-6 bg-orange-100 rounded-full flex items-center justify-center border-2 border-white">
                      <ScanLine className="w-3 h-3 text-orange-500" />
                    </div>
                  )}
                </div>

                <div>
                  <h2 className="text-gray-800" style={{ fontWeight: 600, fontSize: 18 }}>
                    正在解析方案文件…
                  </h2>
                  <p className="text-sm text-gray-500 mt-2">
                    已用时 {elapsedSeconds} 秒 · 预计需要 1-3 分钟
                  </p>
                </div>

                {isScannedDocument && (
                  <div className="bg-orange-50 border border-orange-200 rounded-lg px-4 py-3 text-sm text-orange-700 flex items-start gap-2">
                    <ScanLine className="w-4 h-4 shrink-0 mt-0.5" />
                    <div>
                      <span style={{ fontWeight: 500 }}>扫描件 OCR 精度提示</span>
                      <p className="text-orange-600 mt-0.5">
                        检测到当前文件为扫描件，OCR 精度可能受原始扫描质量影响，请在字段核对阶段重点确认关键字段。
                      </p>
                    </div>
                  </div>
                )}

                <div className="bg-blue-50 rounded-lg px-4 py-3 text-sm text-blue-700">
                  解析完成后将自动进入字段核对步骤，无需手动操作
                  <br />
                  <span className="text-xs text-blue-400 mt-1 block">
                    SSE 连接状态：{sseConnected ? '✓ 已连接' : '连接中…'}
                  </span>
                </div>
              </div>
            )}

            {/* Failed State */}
            {(parseStatus === 'failed' || parseStatus === 'timeout') && (
              <div className="text-center space-y-5">
                <div className="w-16 h-16 bg-red-50 rounded-full flex items-center justify-center mx-auto">
                  <AlertTriangle className="w-8 h-8 text-red-500" />
                </div>
                <div>
                  <h2 className="text-gray-800" style={{ fontWeight: 600, fontSize: 18 }}>
                    {parseStatus === 'timeout' ? '解析超时' : '解析失败'}
                  </h2>
                  <p className="text-sm text-gray-500 mt-2">
                    {parseStatus === 'timeout'
                      ? 'OCR 解析超时（>15分钟），请重试或联系支持'
                      : 'OCR 服务返回错误，请检查文件格式后重试'}
                  </p>
                  <p className="text-xs text-gray-400 mt-1">已重试 {retryCount}/3 次</p>
                </div>

                <div className="space-y-3">
                  <button
                    onClick={handleRetry}
                    disabled={retryCount >= 3 || isRetrying}
                    className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white px-5 py-2.5 rounded-lg text-sm mx-auto transition-colors"
                    style={{ fontWeight: 500 }}
                  >
                    <RotateCcw className={`w-4 h-4 ${isRetrying ? 'animate-spin' : ''}`} />
                    {retryCount >= 3 ? '已达最大重试次数（3次）' : `重新解析（剩余 ${3 - retryCount} 次）`}
                  </button>
                  {retryCount >= 3 && (
                    <p className="text-xs text-red-500">已达最大重试次数，请联系管理员或重新上传文件</p>
                  )}
                </div>
              </div>
            )}

            {/* Abort Area */}
            <div className="mt-8 pt-5 border-t border-gray-100 flex justify-center">
              <button
                onClick={handleAbort}
                disabled={isAborting}
                className="flex items-center gap-2 text-sm text-red-500 hover:text-red-700 hover:bg-red-50 px-4 py-2 rounded-lg transition-colors disabled:opacity-50"
              >
                <XCircle className="w-4 h-4" />
                {isAborting ? '正在放弃…' : '放弃并返回'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
