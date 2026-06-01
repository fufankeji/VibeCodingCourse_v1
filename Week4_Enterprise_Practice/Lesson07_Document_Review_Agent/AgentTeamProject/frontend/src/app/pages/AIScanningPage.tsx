import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router';
import { AlertCircle, Loader2, XCircle } from 'lucide-react';
import { GlobalNav } from '../components/GlobalNav';
import { WorkflowStatusBar } from '../components/WorkflowStatusBar';
import { RiskLevelBadge } from '../components/RiskLevelBadge';
import { subscribeSSE } from '../api/sse';
import { abortSession } from '../api/sessions';

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

  useEffect(() => {
    if (!sessionId) return;

    const tick = setInterval(() => setElapsedSeconds((s) => s + 1), 1000);

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
      } else if (event === 'state_changed') {
        const newState = (data as any).state || (data as any).new_state;
        if (newState === 'hitl_pending' || newState === 'hitl_high_risk') {
          setTimeout(() => navigate(`/contracts/${sessionId}/review`), 500);
        } else if (newState === 'hitl_medium_confirm') {
          setTimeout(() => navigate(`/contracts/${sessionId}/batch`), 500);
        } else if (newState === 'report_ready' || newState === 'completed') {
          setTimeout(() => navigate(`/contracts/${sessionId}/report`), 500);
        }
      }
    });

    return () => {
      clearInterval(tick);
      unsubscribe();
    };
  }, [sessionId, navigate]);

  return (
    <div className="min-h-screen bg-gray-50">
      <GlobalNav />
      <WorkflowStatusBar sessionState="scanning" scanningStarted={true} />
      <main className="pt-[118px]">
        <div className="mx-auto max-w-2xl px-4 py-6 sm:px-6">
          <div className="rounded-lg border border-gray-200 bg-white p-6 shadow-sm sm:p-8">
            <div className="mb-8 text-center">
              <div className="relative mb-4 inline-flex">
                <div className="flex h-16 w-16 items-center justify-center rounded-full bg-blue-50">
                  <Loader2 className="h-8 w-8 animate-spin text-blue-600" />
                </div>
                <div className="absolute inset-0 rounded-full border-2 border-blue-200 opacity-50 animate-ping" />
              </div>
              <h2 className="text-lg font-semibold text-gray-800">AI 正在进行水保方案规则审查…</h2>
              <p className="mt-2 text-sm text-gray-500">
                已用时 {elapsedSeconds} 秒 · {hasScanResult ? '已收到后端审查结果，正在路由下一步' : '等待后端返回真实审查事件'}
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
                  <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-blue-600" />
                  <p>尚未收到后端 scan_progress。此处不再展示模拟维度或自动打勾。</p>
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
            </div>

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
