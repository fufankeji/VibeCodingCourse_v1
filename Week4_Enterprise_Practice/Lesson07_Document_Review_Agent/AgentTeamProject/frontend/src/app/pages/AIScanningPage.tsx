import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { AlertCircle, FileText, Loader2, RotateCcw, XCircle } from 'lucide-react';
import { GlobalNav } from '../components/GlobalNav';
import { WorkflowStatusBar } from '../components/WorkflowStatusBar';
import { RiskLevelBadge } from '../components/RiskLevelBadge';
import { ExtractedFieldsSummary } from '../components/ExtractedFieldsSummary';
import { subscribeSSE } from '../api/sse';
import { abortSession, getReviewPipelineStatus, getSession, startReview } from '../api/sessions';
import { listItems } from '../api/items';
import type { ReviewItem } from '../types';
import type { ReviewPipelineStatusResponse, SessionResponse } from '../api/sessions';

interface ScanProgress {
  high: number;
  medium: number;
  low: number;
  total: number;
}

interface CategoryCount {
  label: string;
  count: number;
}

const STALE_SCANNING_AFTER_MS = 3 * 60 * 1000;

function countsFromItems(items: ReviewItem[], fallbackTotal: number): ScanProgress {
  const progress = items.reduce(
    (acc, item) => {
      if (item.risk_level === 'HIGH') acc.high += 1;
      else if (item.risk_level === 'MEDIUM') acc.medium += 1;
      else if (item.risk_level === 'LOW') acc.low += 1;
      return acc;
    },
    { high: 0, medium: 0, low: 0, total: fallbackTotal }
  );
  progress.total = fallbackTotal || progress.high + progress.medium + progress.low;
  return progress;
}

function categoriesFromItems(items: ReviewItem[]): CategoryCount[] {
  const counts = new Map<string, number>();
  for (const item of items) {
    const label = String(item.risk_category || '未分类').trim() || '未分类';
    counts.set(label, (counts.get(label) || 0) + 1);
  }
  return [...counts.entries()]
    .map(([label, count]) => ({ label, count }))
    .filter((item) => item.count > 0)
    .sort((a, b) => b.count - a.count);
}

function sessionProgress(session: SessionResponse): ScanProgress {
  const summary = session.progress_summary;
  return {
    high: Number(summary?.total_high_risk ?? 0),
    medium: Number(summary?.total_medium_risk ?? 0),
    low: Number(summary?.total_low_risk ?? 0),
    total: Number(summary?.total_high_risk ?? 0) + Number(summary?.total_medium_risk ?? 0) + Number(summary?.total_low_risk ?? 0),
  };
}

function latestFailureMessage(status: ReviewPipelineStatusResponse | null): string {
  const failure = status?.last_failure;
  return String(failure?.message || failure?.user_message || failure?.error || '').trim();
}

function runningStageTitle(status: ReviewPipelineStatusResponse | null): string {
  const running = status?.stages.find((stage) => stage.status === 'running');
  return running?.title || '';
}

function isPipelineStatusRecent(status: ReviewPipelineStatusResponse | null): boolean {
  const updatedAt = Date.parse(status?.updated_at || '');
  return Number.isFinite(updatedAt) && Date.now() - updatedAt < STALE_SCANNING_AFTER_MS;
}

/**
 * AIScanningPage — P07 AI 扫描进度页
 * GET /sessions/{session_id}/events (SSE) — 已开发
 * 收到 scan_progress 事件：更新真实风险计数和类别分布
 * 收到路由事件后跳转：
 *   route_auto_passed → P10 报告页
 *   route_batch_review → P09 批量复核页
 *   route_interrupted → P08 HITL 审核页
 * R01: 严禁显示「无风险」或「扫描通过」等绝对化判断文字
 */
export function AIScanningPage() {
  const { id: sessionId } = useParams();
  const navigate = useNavigate();
  const [progress, setProgress] = useState<ScanProgress>({ high: 0, medium: 0, low: 0, total: 0 });
  const [categories, setCategories] = useState<CategoryCount[]>([]);
  const [hasScanResult, setHasScanResult] = useState(false);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [backendMessage, setBackendMessage] = useState('等待后端返回真实审查事件');
  const [stalledReason, setStalledReason] = useState('');
  const [isRestartingReview, setIsRestartingReview] = useState(false);
  const [restartError, setRestartError] = useState('');

  const pollBackendStatus = useCallback(async () => {
    if (!sessionId) return;
    const [sessionRes, itemsRes, pipelineRes] = await Promise.allSettled([
      getSession(sessionId),
      listItems(sessionId, { limit: 100 }),
      getReviewPipelineStatus(sessionId),
    ]);

    const session = sessionRes.status === 'fulfilled' ? sessionRes.value : null;
    const itemResult = itemsRes.status === 'fulfilled' ? itemsRes.value : null;
    const pipelineStatus = pipelineRes.status === 'fulfilled' ? pipelineRes.value : null;

    if (session) {
      const nextProgress = sessionProgress(session);
      if (nextProgress.total > 0) {
        setProgress(nextProgress);
        setHasScanResult(true);
      }

      if (session.state === 'hitl_pending' || session.state === 'hitl_high_risk') {
        navigate(`/contracts/${sessionId}/review`);
        return;
      }
      if (session.state === 'hitl_medium_confirm') {
        navigate(`/contracts/${sessionId}/batch`);
        return;
      }
      if (session.state === 'completed' || session.state === 'report_ready') {
        navigate(`/contracts/${sessionId}/report`);
        return;
      }
      if (session.state === 'parsed') {
        const reason = latestFailureMessage(pipelineStatus);
        setStalledReason(reason || '后端已回到可重新启动状态，但没有生成审查项。请重新启动清洗与向量审查。');
        setBackendMessage('规则审查没有继续运行');
        return;
      }
      if (session.state === 'aborted') {
        setStalledReason('当前会话已中止，不能继续等待规则审查事件。');
        setBackendMessage('会话已中止');
        return;
      }
    }

    if (itemResult && itemResult.total > 0) {
      const nextProgress = countsFromItems(itemResult.items, itemResult.total);
      setProgress(nextProgress);
      setCategories(categoriesFromItems(itemResult.items));
      setHasScanResult(true);
      setStalledReason('');
      setBackendMessage('已从后端读取到审查项，正在等待路由结果');
      return;
    }

    const runningTitle = runningStageTitle(pipelineStatus);
    const pipelineRecentlyUpdated = isPipelineStatusRecent(pipelineStatus);
    if (runningTitle && pipelineRecentlyUpdated) {
      setStalledReason('');
      setBackendMessage(`后端正在执行：${runningTitle}`);
      return;
    }

    if (session?.state === 'scanning') {
      const updatedAt = Date.parse(session.updated_at);
      const recentlyUpdated = Number.isFinite(updatedAt) && Date.now() - updatedAt < STALE_SCANNING_AFTER_MS;
      if (recentlyUpdated || pipelineRecentlyUpdated) {
        setBackendMessage('后端已进入审查状态，正在等待真实审查项或失败事件');
        return;
      }
      const reason = latestFailureMessage(pipelineStatus);
      const staleRunning = runningTitle ? `后端阶段“${runningTitle}”超过 3 分钟没有更新。` : '';
      setStalledReason(reason || `${staleRunning}当前没有生成审查项，可以重新启动清洗与审查。`);
      setBackendMessage('后端没有活动审查任务');
    }
  }, [sessionId, navigate]);

  useEffect(() => {
    if (!sessionId) return;

    const tick = setInterval(() => setElapsedSeconds((s) => s + 1), 1000);
    void pollBackendStatus();
    const poll = setInterval(() => {
      void pollBackendStatus();
    }, 5000);

    const unsubscribe = subscribeSSE(sessionId, (event, data) => {
      if (event === 'scan_progress') {
        const d = data as any;
        setHasScanResult(true);
        if ('high_count' in d || 'medium_count' in d || 'low_count' in d) {
          setProgress({
            high: Number(d.high_count ?? 0),
            medium: Number(d.medium_count ?? 0),
            low: Number(d.low_count ?? 0),
            total: Number(d.found_count ?? 0),
          });
        } else if (d.risk_level === 'HIGH') {
          setProgress((p) => ({ ...p, high: d.found_count ?? p.high + 1, total: p.total + 1 }));
        } else if (d.risk_level === 'MEDIUM') {
          setProgress((p) => ({ ...p, medium: d.found_count ?? p.medium + 1, total: p.total + 1 }));
        } else if (d.risk_level === 'LOW') {
          setProgress((p) => ({ ...p, low: d.found_count ?? p.low + 1, total: p.total + 1 }));
        }

        const categoryCounts = d.category_counts && typeof d.category_counts === 'object' ? d.category_counts : {};
        setCategories(
          Object.entries(categoryCounts)
            .map(([label, count]) => ({ label, count: Number(count) || 0 }))
            .filter((item) => item.count > 0)
            .sort((a, b) => b.count - a.count)
        );
      } else if (event === 'route_interrupted') {
        setTimeout(() => navigate(`/contracts/${sessionId}/review`), 500);
      } else if (event === 'route_batch_review') {
        setTimeout(() => navigate(`/contracts/${sessionId}/batch`), 500);
      } else if (event === 'route_auto_passed') {
        setTimeout(() => navigate(`/contracts/${sessionId}/report`), 500);
      } else if (event === 'system_failure') {
        const message = String((data as any).message || (data as any).technical_message || '规则审查失败，但后端没有返回具体原因');
        setStalledReason(message);
        setBackendMessage('后端返回规则审查失败');
      } else if (event === 'state_changed') {
        const newState = (data as any).state || (data as any).new_state;
        if (newState === 'hitl_pending' || newState === 'hitl_high_risk') {
          setTimeout(() => navigate(`/contracts/${sessionId}/review`), 500);
        } else if (newState === 'hitl_medium_confirm') {
          setTimeout(() => navigate(`/contracts/${sessionId}/batch`), 500);
        } else if (newState === 'report_ready' || newState === 'completed') {
          setTimeout(() => navigate(`/contracts/${sessionId}/report`), 500);
        } else if (newState === 'parsed') {
          setStalledReason('规则审查已停止，后端已回到可重新启动状态。');
          setBackendMessage('规则审查没有继续运行');
        }
      }
    });

    return () => {
      clearInterval(tick);
      clearInterval(poll);
      unsubscribe();
    };
  }, [sessionId, navigate, pollBackendStatus]);

  const handleRestartReview = async () => {
    if (!sessionId || isRestartingReview) return;
    setIsRestartingReview(true);
    setRestartError('');
    setStalledReason('');
    setBackendMessage('正在重新启动清洗与向量审查');
    try {
      await startReview(sessionId);
      setBackendMessage('已重新启动，等待后端返回真实审查事件');
      await pollBackendStatus();
    } catch (err: any) {
      setRestartError(err.message || '重新启动失败');
      await pollBackendStatus();
    } finally {
      setIsRestartingReview(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <GlobalNav />
      <WorkflowStatusBar sessionState="scanning" scanningStarted={true} />
      <main className="pt-[118px]">
        <div className="mx-auto max-w-2xl px-4 py-6 sm:px-6">
          <div className="mb-4 flex justify-end">
            <button
              type="button"
              onClick={() => sessionId && navigate(`/contracts/${sessionId}/document?stage=routing`)}
              className="inline-flex h-10 items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 shadow-sm transition-colors hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              <FileText className="h-4 w-4" />
              查看解析文档
            </button>
          </div>
          <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
            <div className="mb-8 text-center">
              <div className="relative mb-4 inline-flex">
                <div className={`flex h-16 w-16 items-center justify-center rounded-full ${stalledReason ? 'bg-amber-50' : 'bg-blue-50'}`}>
                  {stalledReason ? (
                    <AlertCircle className="h-8 w-8 text-amber-600" />
                  ) : (
                    <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
                  )}
                </div>
                {!stalledReason && <div className="absolute inset-0 rounded-full border-2 border-blue-200 opacity-50 animate-ping" />}
              </div>
              <h2 className="text-lg font-semibold text-gray-800">
                {stalledReason ? '规则审查没有继续运行' : '正在进行水保方案规则审查…'}
              </h2>
              <p className="mt-2 text-sm text-gray-500">
                已用时 {elapsedSeconds} 秒 · {hasScanResult ? '已收到后端审查结果，正在路由下一步' : backendMessage}
              </p>
            </div>

            <div className="mb-7 grid grid-cols-3 gap-3">
              <div className="rounded-lg border border-red-100 bg-red-50 py-4 text-center">
                <p className="text-2xl font-bold text-red-600">{progress.high}</p>
                <RiskLevelBadge level="HIGH" />
              </div>
              <div className="rounded-lg border border-amber-100 bg-amber-50 py-4 text-center">
                <p className="text-2xl font-bold text-amber-600">{progress.medium}</p>
                <RiskLevelBadge level="MEDIUM" />
              </div>
              <div className="rounded-lg border border-green-100 bg-green-50 py-4 text-center">
                <p className="text-2xl font-bold text-green-600">{progress.low}</p>
                <RiskLevelBadge level="LOW" />
              </div>
            </div>

            <div className="mb-8 rounded-md border border-slate-200 bg-slate-50 p-4">
              <p className="text-xs font-medium text-slate-500">真实审查结果</p>
              {!hasScanResult ? (
                <div className="mt-3 flex items-start gap-2 text-sm text-slate-600">
                  {stalledReason ? (
                    <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                  ) : (
                    <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-blue-600" />
                  )}
                  <p>{stalledReason || '正在等待后端返回真实风险项。当前不会推断未返回的审查项，也不会自动标记通过。'}</p>
                </div>
              ) : categories.length > 0 ? (
                <div className="mt-3 space-y-2">
                  {categories.map((item) => (
                    <div key={item.label} className="flex items-center justify-between gap-3 rounded-md border border-slate-200 bg-white px-3 py-2">
                      <span className="text-sm text-slate-700">{item.label}</span>
                      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">{item.count} 项</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="mt-3 flex items-start gap-2 text-sm text-slate-600">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                  <p>后端已返回审查结果，但没有返回风险类别分布。不能据此判断文档合格。</p>
                </div>
              )}
              {hasScanResult && (
                <p className="mt-3 text-xs text-slate-500">当前仅展示后端返回的风险项汇总；不代表所有规则维度均已通过。</p>
              )}
              {stalledReason && (
                <div className="mt-4 flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={handleRestartReview}
                    disabled={isRestartingReview}
                    className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-blue-600 px-3 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:bg-blue-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                  >
                    {isRestartingReview ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
                    重新启动清洗与审查
                  </button>
                  <button
                    type="button"
                    onClick={() => pollBackendStatus()}
                    className="inline-flex h-10 items-center justify-center rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                  >
                    刷新后端状态
                  </button>
                </div>
              )}
              {restartError && (
                <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                  {restartError}
                </div>
              )}
            </div>

            <ExtractedFieldsSummary sessionId={sessionId} className="mb-8" />

            {hasScanResult && progress.total === 0 && (
              <div className="mb-8 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">
                <div className="flex gap-2">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <p>后端返回 0 条待复核风险项。这不是“文档合格”的证明，可能是文档内容不足、解析质量不足、规则未命中或审查链路降级。</p>
                </div>
              </div>
            )}

            <div className="border-t border-gray-100 pt-5 text-center text-xs text-gray-400">
              等待后端路由事件：route_interrupted / route_batch_review / route_auto_passed
            </div>
          </div>

          <div className="mt-4 flex justify-center">
            <button
              onClick={async () => {
                if (!sessionId) return;
                if (!window.confirm('确定要放弃本次评审流程吗？此操作不可逆。')) return;
                try {
                  await abortSession(sessionId, '用户主动放弃');
                  navigate('/contracts');
                } catch (err: any) {
                  alert(err.message || '放弃失败');
                }
              }}
              className="flex h-11 items-center gap-2 rounded-md px-4 text-sm text-red-500 transition-colors hover:bg-red-50 hover:text-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
            >
              <XCircle className="h-4 w-4" /> 放弃并返回
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
