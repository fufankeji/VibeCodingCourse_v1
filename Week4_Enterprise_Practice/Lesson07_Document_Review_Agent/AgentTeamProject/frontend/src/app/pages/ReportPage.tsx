import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router';
import { Download, FileText, CheckCircle, AlertTriangle, Info, Lock, Loader2 } from 'lucide-react';
import { GlobalNav } from '../components/GlobalNav';
import { WorkflowStatusBar } from '../components/WorkflowStatusBar';
import { RiskLevelBadge } from '../components/RiskLevelBadge';
import { SourceBadge } from '../components/SourceBadge';
import { ConfidenceBadge } from '../components/ConfidenceBadge';
import { getReport, getReportDownloadUrl } from '../api/reports';
import { listItems } from '../api/items';
import { subscribeSSE } from '../api/sse';
import { useAuth } from '../contexts/AuthContext';
import type { ReportData, ReviewItem } from '../types';

/**
 * ReportPage — P10 审核报告页
 * GET /sessions/{session_id}/report — 已开发
 * GET /sessions/{session_id}/report/download?format=pdf|json — 已开发（302 重定向至预签名 URL）
 * GET /sessions/{session_id}/events (SSE) — 等待 report_ready 事件
 *
 * R10: coverage_statement 和 disclaimer 为强制展示元素，不可收起或隐藏
 * R07: decision_history 仅 reviewer/admin 可见
 */
export function ReportPage() {
  const { id: sessionId } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [report, setReport] = useState<ReportData | null>(null);
  const [decidedItems, setDecidedItems] = useState<ReviewItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isReady, setIsReady] = useState(false);
  const [isDownloading, setIsDownloading] = useState<string | null>(null);
  const [showHistoryId, setShowHistoryId] = useState<string | null>(null);

  // Load report and decided items
  useEffect(() => {
    if (!sessionId) return;
    setIsLoading(true);

    const loadReport = async () => {
      try {
        const r = await getReport(sessionId);
        setReport(r);
        setIsReady(r.report_status === 'ready');
      } catch {
        // Report not ready yet, stay in generating state
        setIsReady(false);
      }

      try {
        const itemsRes = await listItems(sessionId, { limit: 100 });
        setDecidedItems(itemsRes.items.filter((i) => i.human_decision !== 'pending'));
      } catch {
        // Items might not be loaded
      }

      setIsLoading(false);
    };

    loadReport();
  }, [sessionId]);

  // SSE for report_ready event
  useEffect(() => {
    if (!sessionId || isReady) return;
    const unsubscribe = subscribeSSE(sessionId, (event) => {
      if (event === 'report_ready') {
        // Reload report
        getReport(sessionId).then((r) => {
          setReport(r);
          setIsReady(true);
        }).catch(() => {});
      }
    });
    return unsubscribe;
  }, [sessionId, isReady]);

  const handleDownload = (format: 'pdf' | 'json') => {
    if (!sessionId) return;
    setIsDownloading(format);
    const url = getReportDownloadUrl(sessionId, format);
    window.open(url, '_blank');
    setTimeout(() => setIsDownloading(null), 1000);
  };

  const riskColor = { high: 'text-red-600', medium: 'text-amber-600', low: 'text-green-600' };

  return (
    <div className="min-h-screen bg-gray-50">
      <GlobalNav />
      <WorkflowStatusBar sessionState={isReady ? 'report_ready' : 'completed'} />

      <div style={{ paddingTop: 78 }}>
        <div className="max-w-4xl mx-auto px-6 py-6">
          {/* Loading State */}
          {isLoading && (
            <div className="flex items-center justify-center py-16 text-gray-400">
              <Loader2 className="w-6 h-6 animate-spin mr-2" /> 正在加载报告…
            </div>
          )}

          {/* Generating State */}
          {!isLoading && !isReady && (
            <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-12 text-center mb-6">
              <div className="w-16 h-16 bg-blue-50 rounded-full flex items-center justify-center mx-auto mb-4">
                <FileText className="w-8 h-8 text-blue-500 animate-pulse" />
              </div>
              <h2 className="text-gray-800" style={{ fontWeight: 600, fontSize: 18 }}>报告生成中…</h2>
              <p className="text-sm text-gray-500 mt-2">正在生成审核报告，请稍候</p>
              <p className="text-xs text-gray-400 mt-1">SSE 监听中，报告就绪后将自动刷新</p>
            </div>
          )}

          {isReady && report && (
            <>
              {/* Header */}
              <div className="flex items-start justify-between mb-6">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <CheckCircle className="w-5 h-5 text-green-500" />
                    <span className="text-sm text-green-600" style={{ fontWeight: 500 }}>报告已就绪（state: report_ready）</span>
                  </div>
                  <h1 className="text-gray-900" style={{ fontSize: 20, fontWeight: 700 }}>审查意见稿</h1>
                  <p className="text-xs text-gray-400 mt-1">
                    生成时间：{new Date(report.generated_at).toLocaleString('zh-CN')} ·
                    GET /sessions/{sessionId}/report
                  </p>
                </div>
                {/* Download Area */}
                <div className="flex gap-2">
                  <button
                    onClick={() => handleDownload('pdf')}
                    disabled={!!isDownloading}
                    className="flex items-center gap-2 bg-red-600 hover:bg-red-700 disabled:bg-gray-300 text-white px-4 py-2 rounded-lg text-sm transition-colors"
                    style={{ fontWeight: 500 }}
                  >
                    <Download className="w-4 h-4" />
                    {isDownloading === 'pdf' ? '下载中…' : '下载 PDF'}
                  </button>
                  <button
                    onClick={() => handleDownload('json')}
                    disabled={!!isDownloading}
                    className="flex items-center gap-2 bg-gray-600 hover:bg-gray-700 disabled:bg-gray-300 text-white px-4 py-2 rounded-lg text-sm transition-colors"
                    style={{ fontWeight: 500 }}
                  >
                    <Download className="w-4 h-4" />
                    {isDownloading === 'json' ? '下载中…' : '下载 JSON'}
                  </button>
                </div>
              </div>

              {/* Summary Card */}
              <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-4">
                <h2 className="text-gray-800 mb-4" style={{ fontWeight: 600, fontSize: 16 }}>执行摘要</h2>
                <div className="grid grid-cols-2 gap-4 mb-4">
                  <div>
                    <p className="text-xs text-gray-500">项目名称</p>
                    <p className="text-sm text-gray-800">{report.summary.project_name || '未提取'}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">建设单位</p>
                    <p className="text-sm text-gray-800">{report.summary.construction_unit || report.summary.contract_parties?.[0] || '未提取'}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">建设地点</p>
                    <p className="text-sm text-gray-800">{report.summary.project_location || '未提取'}</p>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500">水保投资</p>
                    <p className="text-sm text-gray-800">{report.summary.investment_estimate || report.summary.contract_amount || '未提取'}</p>
                  </div>
                </div>

                <div className="flex items-center gap-3 mb-3">
                  <span className="text-sm text-gray-600">整体风险等级：</span>
                  <RiskLevelBadge level={report.summary.overall_risk_level.toUpperCase() as any} size="md" />
                </div>

                {/* R01: summary.conclusion 非绝对化表述，原文展示 */}
                <div className="bg-gray-50 rounded-xl px-4 py-3 text-sm text-gray-700">
                  <span style={{ fontWeight: 500 }}>审核结论：</span>{report.summary.conclusion}
                </div>

                {/* Stats */}
                <div className="mt-4 grid grid-cols-5 gap-2">
                  {[
                    { label: '问题总数', value: report.item_stats.total, color: 'text-gray-700' },
                    { label: '确认', value: report.item_stats.approved, color: 'text-green-600' },
                    { label: '修正', value: report.item_stats.edited, color: 'text-amber-600' },
                    { label: '拒绝', value: report.item_stats.rejected, color: 'text-red-600' },
                    { label: '自动通过', value: report.item_stats.auto_passed, color: 'text-blue-600' },
                  ].map((s) => (
                    <div key={s.label} className="text-center bg-gray-50 rounded-lg py-2">
                      <p className={`text-lg ${s.color}`} style={{ fontWeight: 700 }}>{s.value}</p>
                      <p className="text-xs text-gray-400">{s.label}</p>
                    </div>
                  ))}
                </div>
              </div>

              {/* Detailed Analysis — reviewed items */}
              <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-4">
                <h2 className="text-gray-800 mb-4" style={{ fontWeight: 600, fontSize: 16 }}>详细分析（已复核问题）</h2>
                <div className="space-y-4">
                  {decidedItems.map((item) => (
                    <div key={item.id} className="border border-gray-100 rounded-xl overflow-hidden">
                      <div className="px-4 py-3 bg-gray-50 flex items-center gap-2">
                        <RiskLevelBadge level={item.risk_level} />
                        <SourceBadge sourceType={item.source_type} />
                        <ConfidenceBadge score={item.confidence_score} />
                        <span className={`text-xs ml-auto ${
                          item.human_decision === 'approve' ? 'text-green-600' :
                          item.human_decision === 'edit' ? 'text-amber-600' : 'text-gray-500'
                        }`}>
                          {item.human_decision === 'approve' ? '✓ 已批准' :
                           item.human_decision === 'edit' ? '✎ 已修正' : '✗ 已拒绝'}
                        </span>
                      </div>
                      <div className="px-4 py-3 space-y-2">
                        <div>
                          <p className="text-xs text-gray-400 mb-0.5">AI 判断（ai_finding）</p>
                          <p className="text-sm text-gray-700">{item.ai_finding}</p>
                        </div>
                        {item.human_edited_finding && (
                          <div>
                            <p className="text-xs text-gray-400 mb-0.5">人工修正</p>
                            <p className="text-sm text-amber-700">{item.human_edited_finding}</p>
                          </div>
                        )}
                        {item.human_note && (
                          <div>
                            <p className="text-xs text-gray-400 mb-0.5">处理原因（human_note）</p>
                            <p className="text-sm text-gray-700">"{item.human_note}"</p>
                          </div>
                        )}
                        {item.decided_at && (
                          <p className="text-xs text-gray-400">
                            操作人：{item.decided_by === 'user-001' ? '张三' : item.decided_by} ·
                            时间：{new Date(item.decided_at).toLocaleString('zh-CN')}
                          </p>
                        )}

                        {/* R07: decision_history 仅 reviewer/admin 可见 */}
                        {(user?.role === 'reviewer' || user?.role === 'admin') && item.decision_history && (
                          <div>
                            <button
                              onClick={() => setShowHistoryId((p) => (p === item.id ? null : item.id))}
                              className="text-xs text-gray-400 hover:text-gray-600 flex items-center gap-1"
                            >
                              <Lock className="w-3 h-3" />
                              决策历史（仅 reviewer/admin 可见）
                              {showHistoryId === item.id ? ' ▲' : ' ▼'}
                            </button>
                            {showHistoryId === item.id && (
                              <div className="mt-2 bg-gray-50 rounded p-2 text-xs text-gray-500">
                                {item.decision_history.map((dh) => (
                                  <div key={dh.id} className="border-l-2 border-gray-200 pl-2 mb-1">
                                    {dh.operator_name} · {dh.decision_type} · {new Date(dh.operated_at).toLocaleString('zh-CN')}
                                    <p className="text-gray-400">"{dh.human_note}"</p>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Coverage Statement — R10: 强制展示，不可收起 */}
              <div className="bg-white rounded-2xl border border-blue-200 shadow-sm p-6 mb-4">
                <div className="flex items-center gap-2 mb-3">
                  <Info className="w-4 h-4 text-blue-500" />
                  <h2 className="text-blue-700" style={{ fontWeight: 600, fontSize: 15 }}>
                    覆盖范围声明
                    <span className="ml-2 text-xs bg-blue-100 text-blue-600 px-1.5 py-0.5 rounded border border-blue-200">R10: 强制展示</span>
                  </h2>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-xs text-green-600 mb-1" style={{ fontWeight: 500 }}>✓ 已覆盖条款类型</p>
                    <ul className="space-y-1">
                      {report.coverage_statement.covered_clause_types.map((t) => (
                        <li key={t} className="text-sm text-gray-700 flex items-center gap-1.5">
                          <CheckCircle className="w-3 h-3 text-green-500 shrink-0" />
                          {t}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <p className="text-xs text-orange-600 mb-1" style={{ fontWeight: 500 }}>⚠ 未覆盖条款类型</p>
                    <ul className="space-y-1">
                      {report.coverage_statement.not_covered_clause_types.map((t) => (
                        <li key={t} className="text-sm text-gray-600 flex items-center gap-1.5">
                          <AlertTriangle className="w-3 h-3 text-orange-400 shrink-0" />
                          {t}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>

              {/* Disclaimer — R10: 强制展示，不可收起 */}
              <div className="bg-amber-50 rounded-2xl border border-amber-200 p-5">
                <div className="flex items-center gap-2 mb-2">
                  <AlertTriangle className="w-4 h-4 text-amber-600" />
                  <h2 className="text-amber-700" style={{ fontWeight: 600, fontSize: 15 }}>
                    免责声明
                    <span className="ml-2 text-xs bg-amber-100 text-amber-600 px-1.5 py-0.5 rounded border border-amber-300">R10: 强制展示</span>
                  </h2>
                </div>
                <p className="text-sm text-amber-800 leading-relaxed">{report.disclaimer}</p>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
