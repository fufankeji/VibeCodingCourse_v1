import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router';
import { CheckSquare, Square, AlertTriangle, Info, Loader2 } from 'lucide-react';
import { GlobalNav } from '../components/GlobalNav';
import { WorkflowStatusBar } from '../components/WorkflowStatusBar';
import { RiskLevelBadge } from '../components/RiskLevelBadge';
import { SourceBadge } from '../components/SourceBadge';
import { ConfidenceBadge } from '../components/ConfidenceBadge';
import { listItems, batchConfirm } from '../api/items';
import type { ReviewItem } from '../types';

/**
 * BatchReviewPage — P09 批量复核页
 * GET /sessions/{id}/items?risk_level=medium — 已开发
 * POST /sessions/{id}/items/batch-confirm — 已开发（仅中风险可批量批准）
 *
 * ⚠️ 单条 Reject 操作 — 「未开发」：
 *   api_spec 无中风险条款单条拒绝的独立接口
 *   batch-confirm 仅支持批量批准，无拒绝功能
 */
export function BatchReviewPage() {
  const { id: sessionId } = useParams();
  const navigate = useNavigate();

  const [items, setItems] = useState<ReviewItem[]>([]);
  const [isLoadingItems, setIsLoadingItems] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [batchNote, setBatchNote] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);

  // Load medium-risk items from backend
  useEffect(() => {
    if (!sessionId) return;
    setIsLoadingItems(true);
    listItems(sessionId, { risk_level: 'MEDIUM', limit: 100 })
      .then((res) => setItems(res.items))
      .catch((err) => console.error('Failed to load batch items:', err))
      .finally(() => setIsLoadingItems(false));
  }, [sessionId]);

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const toggleAll = () => {
    if (selectedIds.size === items.length) setSelectedIds(new Set());
    else setSelectedIds(new Set(items.map((i) => i.id)));
  };

  const handleBatchConfirm = async () => {
    if (!sessionId) return;
    setIsSubmitting(true);
    try {
      const result = await batchConfirm(sessionId, Array.from(selectedIds), batchNote);
      setItems((prev) =>
        prev.map((i) =>
          selectedIds.has(i.id)
            ? { ...i, human_decision: 'approve', human_note: batchNote, decided_at: new Date().toISOString() }
            : i
        )
      );
      setShowConfirm(false);
      setSelectedIds(new Set());

      if (result.all_medium_risk_completed) {
        setTimeout(() => navigate(`/contracts/${sessionId}/report`), 600);
      }
    } catch (err: any) {
      alert(`批量确认失败: ${err.message || '未知错误'}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  const selectedItems = items.filter((i) => selectedIds.has(i.id));
  const allCompleted = items.every((i) => i.human_decision !== 'pending');

  return (
    <div className="min-h-screen bg-gray-50">
      <GlobalNav />
      <WorkflowStatusBar sessionState="hitl_pending" hitlSubtype="batch_review" />
      <div style={{ paddingTop: 78 }} className="pb-24">
        <div className="max-w-4xl mx-auto px-6 py-6">
          {/* Header */}
          <div className="mb-5">
            <p className="text-xs text-gray-400 mb-1">session_id: {sessionId}</p>
            <h1 className="text-gray-900" style={{ fontSize: 20, fontWeight: 700 }}>中风险问题批量复核</h1>
            <p className="text-sm text-gray-500 mt-1">
              当前方案以下中风险问题可批量确认。批量确认后将触发审查意见生成。
            </p>
          </div>

          {/* API Notice */}
          <div className="bg-blue-50 border border-blue-200 rounded-xl px-4 py-3 mb-5 flex items-start gap-2">
            <Info className="w-4 h-4 text-blue-500 shrink-0 mt-0.5" />
            <div className="text-xs text-blue-700 space-y-1">
              <p><span style={{ fontWeight: 600 }}>已开发接口：</span>POST /sessions/{sessionId}/items/batch-confirm（仅支持批量批准）</p>
              <p className="text-yellow-700 bg-yellow-50 border border-yellow-200 px-2 py-1 rounded">
                <span style={{ fontWeight: 600 }}>⚠️ 未开发：</span>
                中风险单条 Reject 操作接口 — api_spec 无此接口，当前 Reject 按钮仅为 UI 占位，功能待后端开发
              </p>
            </div>
          </div>

          {/* Select All */}
          <div className="flex items-center gap-3 mb-3 px-1">
            <button
              onClick={toggleAll}
              className="flex items-center gap-1.5 text-sm text-blue-600 hover:text-blue-800"
            >
              {selectedIds.size === items.length
                ? <CheckSquare className="w-4 h-4" />
                : <Square className="w-4 h-4" />
              }
              {selectedIds.size === items.length ? '取消全选' : `全选（共 ${items.length} 条）`}
            </button>
            <span className="text-xs text-gray-400">
              已选 {selectedIds.size} 条 · GET /sessions/{sessionId}/items?risk_level=medium
            </span>
          </div>

          {/* Item List */}
          <div className="space-y-3 mb-6">
            {items.map((item) => {
              const isSelected = selectedIds.has(item.id);
              const isDone = item.human_decision !== 'pending';

              return (
                <div
                  key={item.id}
                  className={`bg-white rounded-xl border transition-colors overflow-hidden ${
                    isSelected ? 'border-blue-400 shadow-sm' : isDone ? 'border-green-200 opacity-75' : 'border-gray-200'
                  }`}
                >
                  <div className="px-4 py-4 flex items-start gap-3">
                    {/* Checkbox — 中风险允许多选，高风险严禁批量操作(R03) */}
                    <button
                      onClick={() => !isDone && toggleSelect(item.id)}
                      disabled={isDone}
                      className="mt-0.5 shrink-0"
                    >
                      {isDone ? (
                        <CheckSquare className="w-4 h-4 text-green-500" />
                      ) : isSelected ? (
                        <CheckSquare className="w-4 h-4 text-blue-500" />
                      ) : (
                        <Square className="w-4 h-4 text-gray-300 hover:text-gray-500" />
                      )}
                    </button>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-2 flex-wrap">
                        <RiskLevelBadge level={item.risk_level} />
                        <SourceBadge sourceType={item.source_type} />
                        <ConfidenceBadge score={item.confidence_score} />
                        {isDone && (
                          <span className="text-xs bg-green-100 text-green-700 px-1.5 py-0.5 rounded">已确认</span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500 mb-1">{item.risk_category}</p>
                      {/* R01: ai_finding 原文展示，不截断不改写 */}
                      <p className="text-sm text-gray-700 leading-relaxed">{item.ai_finding}</p>

                      {/* Evidence */}
                      {item.risk_evidence[0] && (
                        <div
                          className="mt-3 rounded-lg border-l-4 pl-3 py-2 pr-3 text-sm text-gray-700"
                          style={{
                            backgroundColor: item.risk_evidence[0].highlight_color, // R09: 使用后端 highlight_color
                            borderLeftColor: '#F59E0B',
                          }}
                        >
                          <p className="text-xs text-gray-400 mb-0.5">{item.risk_evidence[0].context_before}</p>
                          "{item.risk_evidence[0].evidence_text}"
                        </div>
                      )}
                    </div>

                    {/* Single Action Buttons */}
                    {!isDone && (
                      <div className="flex flex-col gap-2 shrink-0">
                        <button
                          onClick={() => {
                            setSelectedIds(new Set([item.id]));
                            setBatchNote('中风险条款已复核，风险可接受');
                            setShowConfirm(true);
                          }}
                          className="text-xs bg-green-50 border border-green-200 text-green-700 px-3 py-1.5 rounded-lg hover:bg-green-100 transition-colors"
                        >
                          单条确认
                        </button>
                        {/* 单条 Reject — 未开发 */}
                        <button
                          disabled
                          title="未开发：api_spec 无中风险单条拒绝接口"
                          className="text-xs bg-gray-50 border border-gray-200 text-gray-400 px-3 py-1.5 rounded-lg cursor-not-allowed"
                        >
                          Reject
                          <span className="block text-xs text-yellow-600">⚠未开发</span>
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Batch Operation Bar — 底部固定，勾选≥1条时显示 */}
      {selectedIds.size > 0 && (
        <div className="fixed bottom-0 left-0 right-0 bg-white border-t border-gray-200 px-6 py-3 flex items-center justify-between z-30 shadow-lg">
          <span className="text-sm text-gray-600">
            已选 <span className="text-blue-600" style={{ fontWeight: 600 }}>{selectedIds.size}</span> 条中风险条款
          </span>
          <div className="flex items-center gap-3">
            <input
              type="text"
              value={batchNote}
              onChange={(e) => setBatchNote(e.target.value)}
              placeholder="批量确认备注（可选）…"
              className="text-sm border border-gray-200 rounded-lg px-3 py-1.5 w-64 focus:outline-none focus:ring-1 focus:ring-blue-400"
            />
            <button
              onClick={() => setShowConfirm(true)}
              className="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2 rounded-lg text-sm transition-colors"
              style={{ fontWeight: 500 }}
            >
              批量确认（{selectedIds.size}条）
            </button>
          </div>
        </div>
      )}

      {/* All completed */}
      {allCompleted && (
        <div className="fixed bottom-0 left-0 right-0 bg-green-50 border-t border-green-200 px-6 py-3 flex items-center justify-between z-30">
          <span className="text-sm text-green-700" style={{ fontWeight: 500 }}>
            ✓ 全部中风险条款已复核，正在生成审核报告…
          </span>
          <button
            onClick={() => navigate(`/contracts/${sessionId}/report`)}
            className="bg-green-600 hover:bg-green-700 text-white px-4 py-2 rounded-lg text-sm transition-colors"
          >
            查看报告
          </button>
        </div>
      )}

      {/* Confirm Modal */}
      {showConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ backgroundColor: 'rgba(0,0,0,0.4)' }}>
          <div className="bg-white rounded-2xl shadow-2xl p-6 max-w-md w-full mx-4">
            <h3 className="text-gray-800 mb-3" style={{ fontWeight: 600, fontSize: 16 }}>确认批量提交</h3>
            <p className="text-sm text-gray-600 mb-4">
              将对 {selectedItems.length} 条中风险条款提交批量确认（approve）决策。
              此操作将触发报告生成流程。
            </p>
            <div className="bg-gray-50 rounded-xl p-3 mb-4 text-xs text-gray-500">
              POST /sessions/{sessionId}/items/batch-confirm
              <br />
              body: &#123; item_ids: [{selectedItems.map((i) => i.id).join(', ')}], human_note: "{batchNote}" &#125;
            </div>
            <div className="flex gap-3">
              <button
                onClick={handleBatchConfirm}
                disabled={isSubmitting}
                className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white py-2.5 rounded-xl text-sm transition-colors"
                style={{ fontWeight: 500 }}
              >
                {isSubmitting ? '提交中…' : '确认提交'}
              </button>
              <button
                onClick={() => setShowConfirm(false)}
                className="px-5 py-2.5 border border-gray-300 text-gray-600 rounded-xl text-sm hover:bg-gray-50"
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
