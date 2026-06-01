import { useCallback, useEffect, useState } from 'react';
import { AlertCircle, Loader2, RotateCcw } from 'lucide-react';
import {
  getReviewPipelineStatus,
  startReview,
  type ReviewPipelineStatusResponse,
  type SessionResponse,
} from '../../api/sessions';
import { listItems } from '../../api/items';
import { canRestartReview } from '../mode';

export function ScanningStagePanel({
  sessionId,
  session,
  readOnly,
}: {
  sessionId: string;
  session: SessionResponse | null;
  readOnly: boolean;
}) {
  const [status, setStatus] = useState<ReviewPipelineStatusResponse | null>(null);
  const [itemTotal, setItemTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [isRestarting, setIsRestarting] = useState(false);
  const [error, setError] = useState('');

  const refresh = useCallback(async () => {
    if (!sessionId) {
      setStatus(null);
      setItemTotal(0);
      setIsLoading(false);
      return;
    }

    const [pipelineRes, itemsRes] = await Promise.allSettled([
      getReviewPipelineStatus(sessionId),
      listItems(sessionId, { limit: 100 }),
    ]);

    if (pipelineRes.status === 'fulfilled') {
      setStatus(pipelineRes.value);
      setError('');
    } else {
      setError(pipelineRes.reason?.message || '读取审查状态失败');
    }

    if (itemsRes.status === 'fulfilled') {
      setItemTotal(itemsRes.value.total);
    }

    setIsLoading(false);
  }, [sessionId]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const hasFailedStage = Boolean(status?.stages.some((stage) => stage.status === 'failed'));
  const historicalFailureMessage = latestFailureMessage(status);
  const currentFailureMessage = hasFailedStage || session?.state === 'parsed' ? historicalFailureMessage : '';
  const canRestart = canRestartReview(session, Boolean(currentFailureMessage) || hasFailedStage) && !readOnly;

  const restart = async () => {
    if (!canRestart || isRestarting) return;
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
          <p className="mt-1 text-xs text-slate-500">展示后端 pipeline 状态与真实审查项数量。</p>
        </div>
        {isLoading ? <Loader2 className="h-5 w-5 animate-spin text-slate-400" /> : null}
      </div>

      {readOnly ? (
        <p className="mt-3 rounded-md bg-slate-50 p-2 text-xs text-slate-500">
          当前会话只读，不能重新启动清洗与审查。
        </p>
      ) : null}
      {error ? <p className="mt-3 rounded-md bg-red-50 p-2 text-sm text-red-700">{error}</p> : null}
      {currentFailureMessage ? (
        <p className="mt-3 rounded-md bg-amber-50 p-2 text-sm text-amber-800">
          <AlertCircle className="mr-1 inline h-4 w-4" />
          {currentFailureMessage}
        </p>
      ) : null}
      {!currentFailureMessage && historicalFailureMessage ? (
        <p className="mt-3 rounded-md bg-slate-50 p-2 text-xs leading-5 text-slate-500">
          最近失败记录：{historicalFailureMessage}
        </p>
      ) : null}

      <div className="mt-4 space-y-2">
        {(status?.stages ?? []).length ? (
          status?.stages.map((stage) => (
            <div key={stage.id} className="rounded-md border border-slate-200 p-3">
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium text-slate-900">{stage.title}</p>
                <span className={`rounded px-2 py-0.5 text-xs ${stageStatusClass(stage.status)}`}>
                  {stage.status}
                </span>
              </div>
              {stage.message ? <p className="mt-1 text-xs text-slate-500">{stage.message}</p> : null}
              <p className="mt-1 text-xs text-slate-400">
                耗时：{stage.duration_ms ?? '-'} ms · 产物：{stage.artifact_exists ? '存在' : '无'} · 缓存：
                {stage.cache_reusable ? '可复用' : '不可复用'} · 阶段项数：{stage.item_count ?? '-'}
              </p>
            </div>
          ))
        ) : (
          <p className="rounded-md border border-dashed border-slate-200 p-3 text-sm text-slate-500">
            暂无后端 pipeline 状态。
          </p>
        )}
      </div>

      <p className="mt-4 text-sm text-slate-600">已生成审查项：{itemTotal}</p>
      {itemTotal > 0 ? (
        <a
          href={`/contracts/${sessionId}/review`}
          className="mt-3 inline-flex h-10 w-full items-center justify-center rounded-md bg-slate-900 px-3 text-sm font-medium text-white hover:bg-slate-800"
        >
          进入人工复核
        </a>
      ) : null}
      <button
        type="button"
        disabled={!canRestart || isRestarting}
        onClick={restart}
        className="mt-3 inline-flex h-10 w-full items-center justify-center gap-2 rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {isRestarting ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
        重新启动清洗与审查
      </button>
    </aside>
  );
}

function latestFailureMessage(status: ReviewPipelineStatusResponse | null): string {
  const failure = status?.last_failure;
  return String(failure?.user_message || failure?.message || failure?.error || '').trim();
}

function stageStatusClass(status: string): string {
  if (status === 'failed') return 'bg-red-100 text-red-700';
  if (status === 'running') return 'bg-blue-100 text-blue-700';
  if (status === 'completed') return 'bg-green-100 text-green-700';
  if (status === 'cached') return 'bg-cyan-100 text-cyan-700';
  if (status === 'skipped') return 'bg-slate-100 text-slate-500';
  return 'bg-slate-100 text-slate-600';
}
