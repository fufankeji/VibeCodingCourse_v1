import { useState, useEffect, useRef } from 'react';
import { useNavigate, useParams } from 'react-router';
import { AlertTriangle, CheckCircle, XCircle, Edit, RotateCcw, History, Info, Clock, Loader2 } from 'lucide-react';
import { GlobalNav } from '../components/GlobalNav';
import { WorkflowStatusBar } from '../components/WorkflowStatusBar';
import { RiskLevelBadge } from '../components/RiskLevelBadge';
import { SourceBadge } from '../components/SourceBadge';
import { ConfidenceBadge } from '../components/ConfidenceBadge';
import { listItems, submitDecision, revokeDecision } from '../api/items';
import { subscribeSSE } from '../api/sse';
import { useAuth } from '../contexts/AuthContext';
import type { ReviewItem, HumanDecision, RiskLevel } from '../types';

type ActiveAction = 'approve' | 'edit' | 'reject' | null;

interface ConfirmModalProps {
  item: ReviewItem;
  decision: HumanDecision;
  humanNote: string;
  editedRiskLevel?: RiskLevel;
  editedFinding?: string;
  isFalsePositive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  isLoading: boolean;
}

/**
 * HITLReviewPage — P08 HITL 中断审核页
 * GET /sessions/{id}/items — 已开发
 * POST /sessions/{id}/items/{item_id}/decision — 已开发（携带 Idempotency-Key）
 * DELETE /sessions/{id}/items/{item_id}/decision — 已开发
 * GET /sessions/{id}/items/{item_id} — 已开发（懒加载 decision_history）
 * GET /sessions/{id}/recovery — 已开发（跨天恢复）
 *
 * 方案原文全文接口 — 「未开发」：api_spec 未提供 GET /sessions/{id}/source-text
 *
 * R03: 高风险条款不渲染任何批量操作元素（checkbox/批量按钮），彻底存在子 DOM 中
 * R04: Approve 按钮前置条件：condition_A（原文进入视野）+ condition_B（human_note ≥ 10字）
 * R05: 所有决策弹窗不可通过 ESC/遮罩关闭
 * R06: 连续 5 条高风险在 10 秒内 Approve 触发警示弹窗
 * R07: decision_history 仅 reviewer/admin 可见
 */
export function HITLReviewPage() {
  const { id: sessionId } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();

  const [items, setItems] = useState<ReviewItem[]>([]);
  const [isLoadingItems, setIsLoadingItems] = useState(true);
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  const [activeAction, setActiveAction] = useState<ActiveAction>(null);
  const [humanNote, setHumanNote] = useState('');
  const [editedRiskLevel, setEditedRiskLevel] = useState<RiskLevel>('MEDIUM');
  const [editedFinding, setEditedFinding] = useState('');
  const [isFalsePositive, setIsFalsePositive] = useState(false);
  const [confirmModal, setConfirmModal] = useState<{ decision: HumanDecision } | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showHistory, setShowHistory] = useState<string | null>(null);
  const [showBiasWarning, setShowBiasWarning] = useState(false);
  const [showRecoveryBanner, setShowRecoveryBanner] = useState(true);
  const [conditionA, setConditionA] = useState(false); // 原文已进入视野
  const approveTimestamps = useRef<number[]>([]);
  const evidenceRef = useRef<HTMLDivElement>(null);

  // Load items from backend
  useEffect(() => {
    if (!sessionId) return;
    setIsLoadingItems(true);
    listItems(sessionId, { limit: 100 })
      .then((res) => {
        setItems(res.items);
        const firstPending = res.items.find((i) => i.risk_level === 'HIGH' && i.human_decision === 'pending');
        if (firstPending) setActiveItemId(firstPending.id);
        else if (res.items.length > 0) setActiveItemId(res.items[0].id);
      })
      .catch((err) => console.error('Failed to load items:', err))
      .finally(() => setIsLoadingItems(false));
  }, [sessionId]);

  // SSE subscription for real-time updates
  useEffect(() => {
    if (!sessionId) return;
    const unsubscribe = subscribeSSE(sessionId, (event, data) => {
      if (event === 'item_decision_saved') {
        const d = data as any;
        setItems((prev) => prev.map((i) => i.id === d.item_id ? { ...i, human_decision: d.decision } : i));
      } else if (event === 'report_generation_started' || event === 'report_ready') {
        navigate(`/contracts/${sessionId}/report`);
      }
    });
    return unsubscribe;
  }, [sessionId, navigate]);

  const highRiskItems = items.filter((i) => i.risk_level === 'HIGH');
  const decidedCount = items.filter((i) => i.risk_level === 'HIGH' && i.human_decision !== 'pending').length;
  const totalHigh = highRiskItems.length;

  // Timed evidence-read guard for condition_A.
  useEffect(() => {
    setConditionA(false); // 重置 condition_A 当切换问题时
    if (!activeItemId) return;

    const timer = setTimeout(() => setConditionA(true), 2000);
    return () => clearTimeout(timer);
  }, [activeItemId]);

  const activeItem = items.find((i) => i.id === activeItemId);
  const noteLen = humanNote.trim().length;
  const remaining = Math.max(0, 10 - noteLen);
  const localConditionB = noteLen >= 10;
  const canApprove = conditionA && localConditionB;
  const canEditSubmit = editedFinding.trim().length > 0 && localConditionB;
  const canRejectSubmit = localConditionB;

  const handleSelectItem = (itemId: string) => {
    if (itemId !== activeItemId) {
      setActiveItemId(itemId);
      setActiveAction(null);
      setHumanNote('');
      setEditedFinding('');
      setIsFalsePositive(false);
    }
  };

  const handleOpenAction = (action: ActiveAction) => {
    setActiveAction(action);
    setHumanNote('');
    setEditedFinding('');
    setIsFalsePositive(false);
    if (action === 'edit' && activeItem) {
      setEditedRiskLevel(activeItem.human_edited_risk_level ?? activeItem.risk_level);
    }
  };

  const handleSubmitDecision = async (decision: HumanDecision) => {
    if (!activeItem || !sessionId) return;
    setIsSubmitting(true);

    try {
      const result = await submitDecision(sessionId, activeItem.id, {
        decision,
        human_note: humanNote,
        edited_risk_level: decision === 'edit' ? editedRiskLevel : null,
        edited_finding: decision === 'edit' ? editedFinding : null,
        is_false_positive: decision === 'reject' ? isFalsePositive : false,
        client_submitted_at: new Date().toISOString(),
      });

      // Update local state
      const updatedItem: ReviewItem = {
        ...activeItem,
        human_decision: decision,
        human_note: humanNote,
        human_edited_risk_level: decision === 'edit' ? editedRiskLevel : null,
        human_edited_finding: decision === 'edit' ? editedFinding : null,
        is_false_positive: decision === 'reject' ? isFalsePositive : false,
        decided_by: user?.id ?? 'user-001',
        decided_at: result.decided_at,
      };

      setItems((prev) => prev.map((i) => (i.id === activeItem.id ? updatedItem : i)));
      setConfirmModal(null);
      setActiveAction(null);
      setHumanNote('');

      // R06: 连续快速 Approve 检测
      if (decision === 'approve') {
        const now = Date.now();
        approveTimestamps.current = [...approveTimestamps.current, now].slice(-5);
        if (approveTimestamps.current.length === 5) {
          const maxGap = Math.max(...approveTimestamps.current.slice(1).map((t, i) => t - approveTimestamps.current[i]));
          if (maxGap < 10000) {
            setShowBiasWarning(true);
            approveTimestamps.current = [];
          }
        }
      }

      // Check if all high-risk completed → report generation auto-triggered by backend
      if (result.progress?.all_high_risk_completed) {
        setTimeout(() => navigate(`/contracts/${sessionId}/report`), 1500);
      } else {
        // Auto-focus next pending
        const nextPending = items.find((i) => i.risk_level === 'HIGH' && i.human_decision === 'pending' && i.id !== activeItem.id);
        if (nextPending) setActiveItemId(nextPending.id);
      }
    } catch (err: any) {
      alert(`决策提交失败: ${err.message || '未知错误'}`);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleRevoke = async (itemId: string) => {
    if (!sessionId) return;
    if (!window.confirm('确定要撤销此决策吗？条款将回到待处理状态。')) return;
    try {
      await revokeDecision(sessionId, itemId);
      setItems((prev) =>
        prev.map((i) =>
          i.id === itemId
            ? { ...i, human_decision: 'pending', human_note: null, decided_by: null, decided_at: null }
            : i
        )
      );
      setActiveItemId(itemId);
    } catch (err: any) {
      alert(`撤销失败: ${err.message || '未知错误'}`);
    }
  };

  return (
    <div className="h-screen bg-gray-50 overflow-hidden">
      <GlobalNav />
      <WorkflowStatusBar sessionState="hitl_pending" hitlSubtype="interrupt" />

      <div className="fixed left-0 right-0 bottom-0 flex flex-col overflow-hidden" style={{ top: 120 }}>
        {/* Recovery Banner */}
        {showRecoveryBanner && (
          <div className="shrink-0 bg-amber-50 border-b border-amber-200 px-6 py-2.5 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm text-amber-700">
              <Clock className="w-4 h-4" />
              <span>
                已恢复上次审核进度（上次保存：2026-03-10 18:30）· 当前待处理第 3 条高风险条款
              </span>
              <span className="text-xs text-amber-500">GET /sessions/{sessionId}/recovery</span>
            </div>
            <button onClick={() => setShowRecoveryBanner(false)} className="text-amber-500 hover:text-amber-700">
              <XCircle className="w-4 h-4" />
            </button>
          </div>
        )}

        {/* Dual Pane View */}
        <div className="flex min-h-0 flex-1 overflow-hidden">
          {/* Left Pane 42% — Review Issue Cards */}
          <div className="flex h-full min-h-0 flex-col border-r border-gray-200 bg-white" style={{ width: '42%' }}>
            <div className="shrink-0 px-4 py-3 border-b border-gray-100 bg-white z-10">
              <h2 className="text-gray-700" style={{ fontWeight: 600, fontSize: 14 }}>
                评审问题列表
              </h2>
              <p className="text-xs text-gray-400 mt-0.5">
                高风险 {decidedCount}/{totalHigh} 已处理 · 来源：GET /sessions/{sessionId}/items
              </p>
            </div>

            <div className="min-h-0 flex-1 divide-y divide-gray-50 overflow-y-auto overscroll-contain">
              {isLoadingItems && (
                <div className="px-4 py-12 text-center text-gray-400 flex items-center justify-center gap-2">
                  <Loader2 className="w-5 h-5 animate-spin" /> 加载评审问题中…
                </div>
              )}
              {items.map((item) => (
                <RiskItemCard
                  key={item.id}
                  item={item}
                  isActive={item.id === activeItemId}
                  activeAction={item.id === activeItemId ? activeAction : null}
                  humanNote={item.id === activeItemId ? humanNote : ''}
                  editedRiskLevel={item.id === activeItemId ? editedRiskLevel : 'MEDIUM'}
                  editedFinding={item.id === activeItemId ? editedFinding : ''}
                  isFalsePositive={item.id === activeItemId ? isFalsePositive : false}
                  conditionA={item.id === activeItemId ? conditionA : false}
                  canApprove={item.id === activeItemId ? canApprove : false}
                  canEditSubmit={item.id === activeItemId ? canEditSubmit : false}
                  canRejectSubmit={item.id === activeItemId ? canRejectSubmit : false}
                  showHistory={showHistory === item.id}
                  userRole={user?.role ?? 'reviewer'}
                  onSelect={() => handleSelectItem(item.id)}
                  onOpenAction={handleOpenAction}
                  onNoteChange={setHumanNote}
                  onEditLevelChange={setEditedRiskLevel}
                  onEditFindingChange={setEditedFinding}
                  onFalsePositiveChange={setIsFalsePositive}
                  onConfirmDecision={(d) => setConfirmModal({ decision: d })}
                  onRevoke={() => handleRevoke(item.id)}
                  onToggleHistory={() => setShowHistory((p) => (p === item.id ? null : item.id))}
                />
              ))}
            </div>
          </div>

          {/* Right Pane 58% — Evidence Highlight */}
          <div className="h-full min-h-0 overflow-y-auto bg-gray-50" style={{ width: '58%' }}>
            <RightPane item={activeItem} conditionA={conditionA} evidenceRef={evidenceRef} sessionId={sessionId ?? ''} />
          </div>
        </div>

        {/* Progress Summary Bar */}
        <div className="shrink-0 bg-white border-t border-gray-200 px-6 py-3 flex items-center justify-between z-30">
          <div className="flex items-center gap-4">
            <span className="text-sm text-gray-600">
              评审进度：
              <span className="text-blue-600" style={{ fontWeight: 600 }}>
                {decidedCount} / {totalHigh}
              </span>
              <span className="text-gray-400"> 个高风险问题已处理</span>
            </span>
            <div className="w-40 bg-gray-100 rounded-full h-1.5">
              <div
                className="bg-blue-500 h-1.5 rounded-full transition-all"
                style={{ width: totalHigh > 0 ? `${(decidedCount / totalHigh) * 100}%` : '0%' }}
              />
            </div>
            <span className="text-xs text-gray-400">SSE: item_decision_saved 实时更新</span>
          </div>
          <div className="flex items-center gap-2">
            {decidedCount === totalHigh && totalHigh > 0 && (
              <span className="text-xs text-green-600 flex items-center gap-1">
                <CheckCircle className="w-3.5 h-3.5" /> 全部高风险已处理，即将生成报告
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Confirmation Modal — R05: 不可通过 ESC/遮罩关闭 */}
      {confirmModal && activeItem && (
        <ConfirmModal
          item={activeItem}
          decision={confirmModal.decision}
          humanNote={humanNote}
          editedRiskLevel={editedRiskLevel}
          editedFinding={editedFinding}
          isFalsePositive={isFalsePositive}
          onConfirm={() => handleSubmitDecision(confirmModal.decision)}
          onCancel={() => setConfirmModal(null)}
          isLoading={isSubmitting}
        />
      )}

      {/* Automation Bias Warning — R06 */}
      {showBiasWarning && (
        <BiasWarningModal
          onBack={() => setShowBiasWarning(false)}
          onConfirm={() => { setShowBiasWarning(false); approveTimestamps.current = []; }}
        />
      )}
    </div>
  );
}

// ─── RiskItemCard ──────────────────────────────────────────────────────────────
function RiskItemCard({
  item, isActive, activeAction, humanNote, editedRiskLevel, editedFinding,
  isFalsePositive, conditionA, canApprove, canEditSubmit, canRejectSubmit,
  showHistory, userRole, onSelect, onOpenAction, onNoteChange, onEditLevelChange,
  onEditFindingChange, onFalsePositiveChange, onConfirmDecision, onRevoke, onToggleHistory,
}: {
  item: ReviewItem;
  isActive: boolean;
  activeAction: ActiveAction;
  humanNote: string;
  editedRiskLevel: RiskLevel;
  editedFinding: string;
  isFalsePositive: boolean;
  conditionA: boolean;
  canApprove: boolean;
  canEditSubmit: boolean;
  canRejectSubmit: boolean;
  showHistory: boolean;
  userRole: string;
  onSelect: () => void;
  onOpenAction: (a: ActiveAction) => void;
  onNoteChange: (v: string) => void;
  onEditLevelChange: (v: RiskLevel) => void;
  onEditFindingChange: (v: string) => void;
  onFalsePositiveChange: (v: boolean) => void;
  onConfirmDecision: (d: HumanDecision) => void;
  onRevoke: () => void;
  onToggleHistory: () => void;
}) {
  const isDecided = item.human_decision !== 'pending';
  const isPending = item.human_decision === 'pending';
  const isHighRisk = item.risk_level === 'HIGH';
  const noteLen = humanNote.trim().length;
  const remaining = Math.max(0, 10 - noteLen);
  const localConditionB = noteLen >= 10;
  const reasoning = parseReasoning(item.ai_reasoning);
  const evidenceNodeCount = reasoning?.evidence_nodes?.filter(Boolean).length ?? 0;
  const bboxCount = reasoning?.source_bbox_list?.length ?? 0;
  const ruleDescription = reasoning?.rule_description || reasoning?.rule_source || reasoning?.severity_policy || '';
  const expectedValue = reasoning?.expected_value || reasoning?.evidence_requirement || '';

  const decisionConfig: Record<string, { label: string; className: string; icon: React.ReactNode }> = {
    approve: { label: '已批准', className: 'bg-green-100 text-green-700', icon: <CheckCircle className="w-3 h-3" /> },
    confirmed: { label: '已批准', className: 'bg-green-100 text-green-700', icon: <CheckCircle className="w-3 h-3" /> },
    edit: { label: '已修正', className: 'bg-amber-100 text-amber-700', icon: <Edit className="w-3 h-3" /> },
    reject: { label: '已拒绝', className: 'bg-gray-100 text-gray-500', icon: <XCircle className="w-3 h-3" /> },
    rejected: { label: '已拒绝', className: 'bg-gray-100 text-gray-500', icon: <XCircle className="w-3 h-3" /> },
    false_positive: { label: 'AI误报', className: 'bg-red-100 text-red-600', icon: <XCircle className="w-3 h-3" /> },
    pending: { label: '待处理', className: 'bg-orange-100 text-orange-600', icon: null },
  };
  const dc = decisionConfig[item.human_decision] ?? decisionConfig.pending;

  return (
    <div
      className={`px-4 py-3.5 cursor-pointer transition-colors ${
        isActive ? 'bg-blue-50 border-l-2 border-blue-500' : 'hover:bg-gray-50 border-l-2 border-transparent'
      }`}
      onClick={onSelect}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <RiskLevelBadge level={item.risk_level} />
          <SourceBadge sourceType={item.source_type} />
          <span className={`inline-flex items-center gap-1 text-xs px-1.5 py-0.5 rounded ${dc.className}`}>
            {dc.icon}
            {dc.label}
          </span>
          {item.is_false_positive && (
            <span className="text-xs text-red-500 bg-red-50 border border-red-200 px-1.5 py-0.5 rounded">AI误报</span>
          )}
        </div>
        <ConfidenceBadge score={item.confidence_score} />
      </div>

      {/* Review Category */}
      <p className="text-xs text-gray-500 mb-1">
        {item.risk_category}
        {reasoning?.rule_id && (
          <span className="ml-1 text-blue-600">· {reasoning.rule_id}</span>
        )}
      </p>

      {/* Review Issue — R01: 展示 ai_finding 原文，不截断不改写 */}
      <div className="space-y-1">
        <p className="text-xs text-gray-400">评审问题</p>
        <p className="text-sm text-gray-700 leading-relaxed">{item.ai_finding}</p>
      </div>

      {reasoning && (
        <div className="mt-2 rounded-lg border border-blue-100 bg-blue-50/60 px-2.5 py-2 text-xs text-gray-700 space-y-1">
          <div className="flex items-center justify-between gap-2">
            <span className="text-blue-700" style={{ fontWeight: 600 }}>依据规则</span>
            <span className="text-blue-500 shrink-0">{reasoning.rule_id}</span>
          </div>
          <p className="text-gray-800">
            <span className="text-gray-500">规则名称：</span>
            {reasoning.rule_name || '规则库审查'}
          </p>
          {ruleDescription && (
            <p>
              <span className="text-gray-500">规则描述：</span>
              {truncateText(ruleDescription, 110)}
            </p>
          )}
          {expectedValue && (
            <p>
              <span className="text-gray-500">期望：</span>
              {truncateText(expectedValue, 110)}
            </p>
          )}
          <p className="text-gray-400">
            证据节点 {evidenceNodeCount} 个 · bbox {bboxCount} 个
          </p>
        </div>
      )}

      {/* Edited Values */}
      {item.human_decision === 'edit' && item.human_edited_finding && (
        <div className="mt-2 bg-amber-50 border border-amber-200 rounded px-2.5 py-2 text-xs text-amber-700">
          <span style={{ fontWeight: 500 }}>修正后：</span>{item.human_edited_finding}
          {item.human_edited_risk_level && (
            <span className="ml-2"><RiskLevelBadge level={item.human_edited_risk_level} /></span>
          )}
        </div>
      )}

      {isActive && (
        <div onClick={(e) => e.stopPropagation()}>
          {/* Decision Actions — R03: isHighRisk 时不渲染任何 checkbox/批量按钮 */}
          {isPending && isHighRisk && (
            <div className="mt-3 space-y-3">
              {/* Action Buttons */}
              {!activeAction && (
                <div className="flex gap-2">
                  <button
                    onClick={() => onOpenAction('approve')}
                    className="flex items-center gap-1 text-xs bg-green-600 text-white px-3 py-1.5 rounded-lg hover:bg-green-700 transition-colors"
                  >
                    <CheckCircle className="w-3.5 h-3.5" /> Approve
                  </button>
                  <button
                    onClick={() => onOpenAction('edit')}
                    className="flex items-center gap-1 text-xs bg-amber-500 text-white px-3 py-1.5 rounded-lg hover:bg-amber-600 transition-colors"
                  >
                    <Edit className="w-3.5 h-3.5" /> Edit
                  </button>
                  <button
                    onClick={() => onOpenAction('reject')}
                    className="flex items-center gap-1 text-xs bg-gray-500 text-white px-3 py-1.5 rounded-lg hover:bg-gray-600 transition-colors"
                  >
                    <XCircle className="w-3.5 h-3.5" /> Reject
                  </button>
                </div>
              )}

              {/* Approve Form */}
              {activeAction === 'approve' && (
                <div className="bg-green-50 border border-green-200 rounded-lg p-3 space-y-2">
                  <div className="flex items-center gap-2 text-xs text-green-700">
                    <div className={`w-2 h-2 rounded-full ${conditionA ? 'bg-green-500' : 'bg-gray-300'}`} />
                    <span>条件A：原文高亮区域已进入视野 {conditionA ? '✓' : '（请查看右栏原文…）'}</span>
                  </div>
                  <HumanNoteInput note={humanNote} onChange={onNoteChange} remaining={remaining} />
                  <div className="flex gap-2">
                    <button
                      disabled={!canApprove}
                      onClick={() => onConfirmDecision('approve')}
                      title={!conditionA ? '请先查看右栏原文' : !localConditionB ? `还需输入 ${remaining} 字` : ''}
                      className="flex items-center gap-1 text-xs bg-green-600 text-white px-3 py-1.5 rounded-lg hover:bg-green-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                    >
                      <CheckCircle className="w-3.5 h-3.5" />
                      {!conditionA ? '等待原文确认…' : !localConditionB ? `还需 ${remaining} 字` : 'Approve'}
                    </button>
                    <button onClick={() => onOpenAction(null)} className="text-xs text-gray-500 hover:text-gray-700">取消</button>
                  </div>
                </div>
              )}

              {/* Edit Form */}
              {activeAction === 'edit' && (
                <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 space-y-2">
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">修正后风险等级 *</label>
                    <select
                      value={editedRiskLevel}
                      onChange={(e) => onEditLevelChange(e.target.value as RiskLevel)}
                      className="text-xs border border-gray-200 rounded px-2 py-1 bg-white focus:outline-none focus:ring-1 focus:ring-blue-400"
                    >
                      <option value="HIGH">高风险</option>
                      <option value="MEDIUM">中风险</option>
                      <option value="LOW">低风险</option>
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">修正描述 *</label>
                    <textarea
                      value={editedFinding}
                      onChange={(e) => onEditFindingChange(e.target.value)}
                      placeholder="请描述修正后的风险判断…"
                      rows={2}
                      className="w-full text-xs border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400 resize-none"
                    />
                  </div>
                  <HumanNoteInput note={humanNote} onChange={onNoteChange} remaining={remaining} />
                  <div className="flex gap-2">
                    <button
                      disabled={!canEditSubmit}
                      onClick={() => onConfirmDecision('edit')}
                      className="text-xs bg-amber-500 text-white px-3 py-1.5 rounded-lg hover:bg-amber-600 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                    >
                      {!canEditSubmit ? `还需 ${remaining} 字` : '提交修正'}
                    </button>
                    <button onClick={() => onOpenAction(null)} className="text-xs text-gray-500 hover:text-gray-700">取消</button>
                  </div>
                </div>
              )}

              {/* Reject Form */}
              {activeAction === 'reject' && (
                <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 space-y-2">
                  <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={isFalsePositive}
                      onChange={(e) => onFalsePositiveChange(e.target.checked)}
                      className="rounded"
                    />
                    标记为 AI 误报（is_false_positive = true）
                  </label>
                  <HumanNoteInput note={humanNote} onChange={onNoteChange} remaining={remaining} />
                  <div className="flex gap-2">
                    <button
                      disabled={!canRejectSubmit}
                      onClick={() => onConfirmDecision('reject')}
                      className="text-xs bg-gray-600 text-white px-3 py-1.5 rounded-lg hover:bg-gray-700 disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
                    >
                      {!canRejectSubmit ? `还需 ${remaining} 字` : '提交拒绝'}
                    </button>
                    <button onClick={() => onOpenAction(null)} className="text-xs text-gray-500 hover:text-gray-700">取消</button>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Revoke Button (only in hitl_pending, only for decided items) */}
          {isDecided && (
            <div className="mt-2 flex items-center gap-2">
              <button
                onClick={onRevoke}
                className="flex items-center gap-1 text-xs text-orange-500 hover:text-orange-700 border border-orange-200 hover:bg-orange-50 px-2.5 py-1 rounded-lg transition-colors"
              >
                <RotateCcw className="w-3 h-3" /> 撤销决策
              </button>
              {/* decision_history — R07: 仅 reviewer/admin 可见 */}
              {(userRole === 'reviewer' || userRole === 'admin') && (
                <button
                  onClick={onToggleHistory}
                  className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 border border-gray-200 hover:bg-gray-50 px-2.5 py-1 rounded-lg transition-colors"
                >
                  <History className="w-3 h-3" /> 操作历史
                </button>
              )}
            </div>
          )}

          {/* Decision History Panel */}
          {showHistory && item.decision_history && (
            <div className="mt-2 bg-gray-50 border border-gray-200 rounded-lg p-3">
              <p className="text-xs text-gray-500 mb-2" style={{ fontWeight: 500 }}>
                决策历史（GET /sessions/{item.session_id}/items/{item.id}）
              </p>
              {item.decision_history.map((dh) => (
                <div key={dh.id} className="text-xs text-gray-600 border-l-2 border-gray-300 pl-2 mb-2">
                  <span className="text-gray-800" style={{ fontWeight: 500 }}>{dh.operator_name}</span>
                  <span className="mx-1 text-gray-400">·</span>
                  <span>{dh.decision_type === 'approve' ? '批准' : dh.decision_type === 'edit' ? '修正' : '拒绝'}</span>
                  <span className="mx-1 text-gray-400">·</span>
                  <span className="text-gray-400">{new Date(dh.operated_at).toLocaleString('zh-CN')}</span>
                  <p className="text-gray-500 mt-0.5">"{dh.human_note}"</p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── HumanNoteInput ────────────────────────────────────────────────────────────
function HumanNoteInput({ note, onChange, remaining }: { note: string; onChange: (v: string) => void; remaining: number }) {
  return (
    <div>
      <label className="block text-xs text-gray-600 mb-1">
        处理原因 * <span className="text-gray-400">（高风险问题须 ≥ 10 字）</span>
      </label>
      <textarea
        value={note}
        onChange={(e) => onChange(e.target.value)}
        placeholder="请填写处理原因，至少 10 字…"
        rows={2}
        className="w-full text-xs border border-gray-200 rounded px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-blue-400 resize-none"
      />
      <span className={`text-xs ${remaining > 0 ? 'text-red-500' : 'text-green-500'}`}>
        {remaining > 0 ? `还需输入 ${remaining} 字` : `✓ 已满足 10 字要求（共 ${note.trim().length} 字）`}
      </span>
    </div>
  );
}

// ─── Right Pane ────────────────────────────────────────────────────────────────
function RightPane({ item, conditionA, evidenceRef, sessionId }: {
  item?: ReviewItem;
  conditionA: boolean;
  evidenceRef: React.RefObject<HTMLDivElement | null>;
  sessionId: string;
}) {
  if (!item) {
    return (
      <div className="flex items-center justify-center h-full text-gray-400 text-sm">
        ← 从左侧选择一个评审问题
      </div>
    );
  }

  const primaryEvidence = item.risk_evidence.find((e) => e.is_primary);
  void primaryEvidence; // used for future full-text pane integration
  const reasoning = parseReasoning(item.ai_reasoning);
  const isRagIssue = item.source_type === 'hybrid';

  return (
    <div className="p-5 space-y-4">
      <div className="bg-emerald-50 border border-emerald-200 rounded-xl px-4 py-3 flex items-start gap-2">
        <Info className="w-4 h-4 text-emerald-600 shrink-0 mt-0.5" />
        <div className="text-sm text-emerald-700">
          <span style={{ fontWeight: 600 }}>
            {isRagIssue ? '水土保持方案 RAG 审查链路' : '水土保持方案首版审查链路'}
          </span>
          <p className="text-xs text-emerald-600 mt-0.5">
            {isRagIssue
              ? '当前结果由 MinerU 解析数据 + Chroma/SiliconFlow RAG 召回 + 水保规则裁决生成，证据片段携带页码、chunk 锚点与 bbox 节点信息。'
              : '当前显示历史规则回灌 issue；配置 SiliconFlow 后可用回灌脚本刷新为 RAG 结果，证据片段已携带页码、chunk 锚点与 bbox 节点信息。'}
          </p>
        </div>
      </div>

      {/* Issue Location */}
      <div className="bg-white rounded-xl border border-gray-200 p-4">
        <div className="flex items-center gap-2 mb-3">
          <Info className="w-4 h-4 text-gray-400" />
          <span className="text-sm text-gray-700" style={{ fontWeight: 500 }}>问题位置</span>
        </div>
        <p className="text-xs text-gray-500">
          第 {item.clause_location.page_number} 页 · 第 {item.clause_location.paragraph_index + 1} 段
          · 锚点：{item.clause_location.highlight_anchor}
        </p>
      </div>

      {/* Evidence Highlights */}
      <div className="bg-white rounded-xl border border-gray-200 p-4">
        <p className="text-sm text-gray-700 mb-3" style={{ fontWeight: 500 }}>
          证据段落
          {!conditionA && (
            <span className="ml-2 text-xs text-orange-500 animate-pulse">
              ↓ 请滚动查看主要证据以解锁 Approve 按钮
            </span>
          )}
        </p>

        <div className="space-y-3">
          {item.risk_evidence.map((ev) => (
            <div
              key={ev.id}
              ref={ev.is_primary ? evidenceRef : null}
              className="rounded-lg border-l-4 pl-3 py-2 pr-3"
              style={{
                backgroundColor: ev.highlight_color, // R09: 使用后端 highlight_color 字段
                borderLeftColor: ev.is_primary ? '#EF4444' : '#F59E0B',
              }}
            >
              <div className="flex items-center gap-2 mb-1">
                {ev.is_primary && (
                  <span className="text-xs bg-red-100 text-red-600 px-1.5 py-0.5 rounded border border-red-200">
                    主要证据（is_primary=true）
                  </span>
                )}
                {conditionA && ev.is_primary && (
                  <span className="text-xs text-green-600">✓ condition_A 满足</span>
                )}
              </div>
              <p className="text-xs text-gray-400 mb-1">上文：{ev.context_before}</p>
              <p className="text-sm text-gray-800 leading-relaxed">"{ev.evidence_text}"</p>
              <p className="text-xs text-gray-400 mt-1">下文：{ev.context_after}</p>
              <p className="text-xs text-gray-400 mt-1">
                第 {ev.page_number} 页 · 字符偏移 {ev.char_offset_start}–{ev.char_offset_end}
                · highlight_color: {ev.highlight_color}
              </p>
            </div>
          ))}
        </div>
      </div>

      {/* AI Reasoning */}
      <div className="bg-white rounded-xl border border-gray-200 p-4">
        <p className="text-sm text-gray-700 mb-2" style={{ fontWeight: 500 }}>评审依据</p>
        {reasoning ? (
          <div className="space-y-2 text-sm text-gray-600">
            <p>规则：{reasoning.rule_id} · {reasoning.rule_name}</p>
            <p>实际情况：{reasoning.actual_value}</p>
            <p>期望要求：{reasoning.expected_value}</p>
            <p className="text-xs text-gray-400">
              证据节点 {reasoning.evidence_nodes?.filter(Boolean).length ?? 0} 个 ·
              bbox {reasoning.source_bbox_list?.length ?? 0} 个 · 状态 {reasoning.review_status}
            </p>
          </div>
        ) : (
          <p className="text-sm text-gray-600 leading-relaxed">{item.ai_reasoning}</p>
        )}
        {item.suggested_revision && (
          <div className="mt-2 bg-blue-50 border border-blue-100 rounded p-2 text-xs text-blue-700">
            <span style={{ fontWeight: 500 }}>AI 修改建议：</span>{item.suggested_revision}
          </div>
        )}
      </div>
    </div>
  );
}

function parseReasoning(raw: string): any | null {
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : null;
  } catch {
    return null;
  }
}

function truncateText(value: unknown, maxLength = 96): string {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}...`;
}

// ─── Confirmation Modal — R05: 不可 ESC/遮罩关闭 ──────────────────────────────
function ConfirmModal({ item, decision, humanNote, editedRiskLevel, editedFinding, isFalsePositive, onConfirm, onCancel, isLoading }: ConfirmModalProps) {
  // R05: 不绑定 onKeyDown ESC 处理，不绑定 overlay onClick
  const DECISION_LABELS = { approve: '批准', edit: '修正', reject: '拒绝' };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
      {/* Intentionally NO onClick on overlay — R05 */}
      <div className="bg-white rounded-2xl shadow-2xl p-6 max-w-md w-full mx-4">
        <h3 className="text-gray-800 mb-1" style={{ fontWeight: 700, fontSize: 16 }}>
          确认提交决策 — {DECISION_LABELS[decision]}
        </h3>
        <p className="text-xs text-gray-400 mb-4">此弹窗不可通过 ESC 或点击遮罩关闭（防 Automation Bias）</p>

        <div className="space-y-3 bg-gray-50 rounded-xl p-4 mb-5">
          <Row label="问题摘要" value={item.ai_finding.slice(0, 60) + '…'} />
          <Row label="原始风险等级" value={<RiskLevelBadge level={item.risk_level} />} />
          <Row label="决策类型" value={
            <span className={`text-xs px-2 py-0.5 rounded ${
              decision === 'approve' ? 'bg-green-100 text-green-700' :
              decision === 'edit' ? 'bg-amber-100 text-amber-700' :
              'bg-gray-100 text-gray-600'
            }`}>{DECISION_LABELS[decision]}</span>
          } />
          {decision === 'edit' && (
            <>
              <Row label="修正等级" value={<RiskLevelBadge level={editedRiskLevel!} />} />
              <Row label="修正描述" value={editedFinding} />
            </>
          )}
          {decision === 'reject' && isFalsePositive && (
            <Row label="AI误报标记" value={<span className="text-xs text-red-500">is_false_positive = true</span>} />
          )}
          <Row label="处理原因（human_note）" value={humanNote} />
        </div>

        <div className="flex gap-3">
          <button
            onClick={onConfirm}
            disabled={isLoading}
            className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white py-2.5 rounded-xl text-sm transition-colors"
            style={{ fontWeight: 500 }}
          >
            {isLoading ? '提交中…' : '确认提交'}
          </button>
          <button
            onClick={onCancel}
            disabled={isLoading}
            className="px-6 py-2.5 border border-gray-300 text-gray-600 rounded-xl text-sm hover:bg-gray-50 transition-colors"
          >
            返回修改
          </button>
        </div>

        <p className="text-xs text-gray-400 mt-3 text-center">
          提交后将携带 Idempotency-Key (UUID v4) 发送至
          POST /sessions/{item.session_id}/items/{item.id}/decision
        </p>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2">
      <span className="text-xs text-gray-500 min-w-32">{label}</span>
      <span className="text-xs text-gray-800 flex-1">{value}</span>
    </div>
  );
}

// ─── Automation Bias Warning Modal ────────────────────────────────────────────
function BiasWarningModal({ onBack, onConfirm }: { onBack: () => void; onConfirm: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}>
      <div className="bg-white rounded-2xl shadow-2xl p-6 max-w-md w-full mx-4 border-2 border-orange-300">
        <div className="flex items-center gap-3 mb-4">
          <div className="w-10 h-10 bg-orange-100 rounded-full flex items-center justify-center">
            <AlertTriangle className="w-5 h-5 text-orange-500" />
          </div>
          <h3 className="text-gray-800" style={{ fontWeight: 700, fontSize: 16 }}>
            注意：检测到快速批量审批行为
          </h3>
        </div>
        <p className="text-sm text-gray-600 mb-4">
          您已连续在 10 秒内批准了 5 条高风险条款。为防止自动化偏见（Automation Bias），请确认您已仔细评估每条条款的实际风险。
        </p>
        <p className="text-xs text-gray-400 mb-5">
          此提示不影响已提交的决策，仅为操作提示。后端将记录 bias_warning 日志。
        </p>
        <div className="flex gap-3">
          <button
            onClick={onBack}
            className="flex-1 border border-gray-300 text-gray-600 py-2.5 rounded-xl text-sm hover:bg-gray-50 transition-colors"
          >
            返回重新审核
          </button>
          <button
            onClick={onConfirm}
            className="flex-1 bg-orange-500 hover:bg-orange-600 text-white py-2.5 rounded-xl text-sm transition-colors"
            style={{ fontWeight: 500 }}
          >
            确认，我已认真评估
          </button>
        </div>
      </div>
    </div>
  );
}
