import { useState, useEffect, useRef } from 'react';
import { useNavigate, useParams } from 'react-router';
import { AlertTriangle, CheckCircle, XCircle, Edit, RotateCcw, History, Info, Loader2, X } from 'lucide-react';
import { RiskLevelBadge } from '../components/RiskLevelBadge';
import { SourceBadge } from '../components/SourceBadge';
import { ConfidenceBadge } from '../components/ConfidenceBadge';
import { ExtractedFieldsSummary } from '../components/ExtractedFieldsSummary';
import { API_BASE_URL } from '../api/client';
import { listItems, submitDecision, revokeDecision } from '../api/items';
import {
  getReviewDocumentContent,
  getReviewRuleTopics,
  getSession,
  runRetrievalDebug,
  type ReviewDocumentContentResponse,
  type ReviewDocumentPage,
  type ReviewDocumentBlock,
  type ReviewRuleTopic,
  type ReviewRuleItem,
  type ReviewCheckItem,
  type RetrievalDebugResponse,
} from '../api/sessions';
import {
  createCheckItem,
  deleteCheckItem,
  listExecutorTypes,
  previewCheckItem,
  updateCheckItem,
  type CheckItemPayload,
  type EvidenceAnchor,
  type ExecutorType,
  type ExpertReviewBrief,
  type EvidenceSlotPackage,
  type FormulaCheckResults,
  type PreviewAgentTrace,
  type PreviewCheckItemResponse,
  type ProjectCompositionConsistency,
  type ProjectCompositionSource,
  type RetrievalMatch,
} from '../api/reviewConfig';
import { subscribeSSE } from '../api/sse';
import { useAuth } from '../contexts/AuthContext';
import type { ReviewItem, HumanDecision, RiskLevel, ReviewResult } from '../types';

type ActiveAction = 'approve' | 'edit' | 'reject' | null;
type ConfigDraft = {
  id?: string;
  topic_id: string;
  rule_id: string;
  executor_type_id: string;
  review_type: string;
  review_sub_type: string;
  conclusion: string;
  baseEvidenceScope: Record<string, unknown>;
  evidenceChaptersInput: string;
  evidenceTablesInput: string;
  evidenceAttachmentsInput: string;
  evidenceRegulationsInput: string;
  targetFieldsInput: string;
  regulationClausesInput: string;
  reviewCriteria: string;
  expectedResult: string;
  failureConditionsInput: string;
  evidenceSlotsJson: string;
  formulaChecksJson: string;
  expertBrief: ExpertReviewBrief;
  sourceRuleSnapshot: Record<string, unknown>;
  advancedDirty: boolean;
  enabled: boolean;
};

type TopicRuleOption = {
  rule_id: string;
  label: string;
};

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
  const [documentContent, setDocumentContent] = useState<ReviewDocumentContentResponse | null>(null);
  const [activeDocumentPage, setActiveDocumentPage] = useState(1);
  const [isLoadingDocument, setIsLoadingDocument] = useState(true);
  const [ruleTopics, setRuleTopics] = useState<ReviewRuleTopic[]>([]);
  const [executorTypes, setExecutorTypes] = useState<ExecutorType[]>([]);
  const [activeRuleTopicId, setActiveRuleTopicId] = useState<string | null>(null);
  const [configDraft, setConfigDraft] = useState<ConfigDraft | null>(null);
  const [previewResult, setPreviewResult] = useState<PreviewCheckItemResponse | null>(null);
  const [retrievalDebugResult, setRetrievalDebugResult] = useState<RetrievalDebugResponse | null>(null);
  const [retrievalDebugError, setRetrievalDebugError] = useState<string | null>(null);
  const [activeEvidenceAnchors, setActiveEvidenceAnchors] = useState<EvidenceAnchor[]>([]);
  const [isRetrievalDebugging, setIsRetrievalDebugging] = useState(false);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isSavingConfig, setIsSavingConfig] = useState(false);
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
  const [readOnly, setReadOnly] = useState(false);
  const [conditionA, setConditionA] = useState(false); // 原文已进入视野
  const approveTimestamps = useRef<number[]>([]);
  const previewRequestSeq = useRef(0);
  const evidenceRef = useRef<HTMLDivElement>(null);

  // Load items from backend
  useEffect(() => {
    if (!sessionId) return;
    getSession(sessionId)
      .then((session) => setReadOnly(Boolean(session.read_only || session.state === 'aborted')))
      .catch(() => {});
    setIsLoadingItems(true);
    listItems(sessionId, { limit: 100 })
      .then((res) => {
        setItems(res.items);
        const firstPending = res.items.find((i) => i.risk_level === 'HIGH' && i.human_decision === 'pending');
        if (firstPending) setActiveItemId(firstPending.id);
        else if (res.items.length > 0) setActiveItemId(res.items[0].id);
        else setActiveItemId(null);
      })
      .catch((err) => console.error('Failed to load items:', err))
      .finally(() => setIsLoadingItems(false));
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    setIsLoadingDocument(true);
    getReviewDocumentContent(sessionId)
      .then((res) => {
        setDocumentContent(res);
        setActiveDocumentPage((current) => (
          res.pages.some((page) => page.page_number === current)
            ? current
            : (res.pages[0]?.page_number ?? 1)
        ));
      })
      .catch((err) => {
        console.error('Failed to load review document content:', err);
        setDocumentContent(null);
      })
      .finally(() => setIsLoadingDocument(false));
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    loadRuleTopics(sessionId)
      .then((res) => {
        setRuleTopics(res.topics);
        setActiveRuleTopicId((current) => current ?? res.topics[0]?.topic_id ?? null);
      })
      .catch((err) => console.error('Failed to load review rule topics:', err));
  }, [sessionId]);

  useEffect(() => {
    listExecutorTypes()
      .then((res) => setExecutorTypes(res.items))
      .catch((err) => console.error('Failed to load executor types:', err));
  }, []);

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
  useEffect(() => {
    if (!activeItem) {
      setActiveEvidenceAnchors([]);
      return;
    }
    const anchors = getReviewItemEvidenceAnchors(activeItem, documentContent);
    setActiveEvidenceAnchors(anchors);
    const anchorPage = anchors.find((anchor) => typeof anchor.page === 'number' && anchor.page > 0)?.page;
    const pageNumber = activeItem?.clause_location?.page_number;
    if (typeof anchorPage === 'number' && anchorPage > 0) {
      setActiveDocumentPage(anchorPage);
    } else if (typeof pageNumber === 'number' && pageNumber > 0) {
      setActiveDocumentPage(pageNumber);
    }
  }, [activeItem?.id, activeItem?.clause_location?.page_number, documentContent]);

  const activeRuleTopic = ruleTopics.find((topic) => topic.topic_id === activeRuleTopicId) ?? ruleTopics[0];
  const noteLen = humanNote.trim().length;
  const remaining = Math.max(0, 10 - noteLen);
  const localConditionB = noteLen >= 10;
  const canApprove = conditionA && localConditionB;
  const canEditSubmit = editedFinding.trim().length > 0 && localConditionB;
  const canRejectSubmit = localConditionB;
  const draftRuleTopic = configDraft
    ? ruleTopics.find((topic) => topic.topic_id === configDraft.topic_id) ?? activeRuleTopic
    : undefined;
  const draftRuleOptions = getTopicRuleOptions(draftRuleTopic);
  const draftRuleOptionsWithCurrent = configDraft?.rule_id && !draftRuleOptions.some((item) => item.rule_id === configDraft.rule_id)
    ? [{ rule_id: configDraft.rule_id, label: `${configDraft.rule_id}（当前绑定）` }, ...draftRuleOptions]
    : draftRuleOptions;
  const executorOptions = executorTypes.length > 0
    ? executorTypes
    : [{ id: 'manual_basic', label: '人工基础核验', description: '', enabled: true }];
  const selectedExecutor = configDraft
    ? executorOptions.find((item) => item.id === configDraft.executor_type_id)
    : undefined;
  const executorBindingBlocked = Boolean(configDraft?.enabled && selectedExecutor && !selectedExecutor.enabled);

  const handleSelectItem = (itemId: string) => {
    if (itemId !== activeItemId) {
      setActiveItemId(itemId);
      setActiveEvidenceAnchors([]);
      setActiveAction(null);
      setHumanNote('');
      setEditedFinding('');
      setIsFalsePositive(false);
    }
  };

  const refreshRuleTopics = async () => {
    if (!sessionId) return;
    const res = await loadRuleTopics(sessionId);
    setRuleTopics(res.topics);
    setActiveRuleTopicId((current) => current ?? res.topics[0]?.topic_id ?? null);
  };

  const resetPreviewState = () => {
    previewRequestSeq.current += 1;
    setPreviewResult(null);
    setActiveEvidenceAnchors([]);
    setIsPreviewing(false);
  };

  const openCreateCheckItem = () => {
    if (readOnly) return;
    if (!activeRuleTopic) return;
    const executor = executorTypes.find((item) => item.enabled) ?? executorTypes[0];
    resetPreviewState();
    setConfigDraft({
      topic_id: activeRuleTopic.topic_id,
      rule_id: '',
      executor_type_id: executor?.id ?? 'manual_basic',
      review_type: executor?.label ?? '人工基础核验',
      review_sub_type: `${activeRuleTopic.topic_name}审查项`,
      conclusion: '',
      baseEvidenceScope: {},
      evidenceChaptersInput: '',
      evidenceTablesInput: '',
      evidenceAttachmentsInput: '',
      evidenceRegulationsInput: '',
      targetFieldsInput: '',
      regulationClausesInput: '',
      reviewCriteria: '',
      expectedResult: '',
      failureConditionsInput: '',
      evidenceSlotsJson: '[]',
      formulaChecksJson: '[]',
      expertBrief: createEmptyExpertBrief(`${activeRuleTopic.topic_name}审查项`),
      sourceRuleSnapshot: {},
      advancedDirty: false,
      enabled: true,
    });
  };

  const openConvertCheckItem = (item: ReviewCheckItem) => {
    if (readOnly) return;
    if (!activeRuleTopic) return;
    const executor = executorTypes.find((candidate) => candidate.enabled) ?? executorTypes[0];
    resetPreviewState();
    setConfigDraft(draftFromRuleTemplate(activeRuleTopic, item, executor));
  };

  const openEditCheckItem = (item: ReviewCheckItem) => {
    if (readOnly) return;
    if (item.ai_or_human_source !== 'configured_checklist') return;
    resetPreviewState();
    setConfigDraft(draftFromItem(item));
  };

  const saveCheckItemDraft = async () => {
    if (!configDraft || readOnly) return;
    setIsSavingConfig(true);
    try {
      const payload = buildCheckItemPayload(configDraft);
      if (configDraft.id) await updateCheckItem(configDraft.id, payload);
      else await createCheckItem(payload);
      resetPreviewState();
      setConfigDraft(null);
      await refreshRuleTopics();
    } catch (err) {
      window.alert(`保存审查项失败：${getErrorMessage(err)}`);
    } finally {
      setIsSavingConfig(false);
    }
  };

  const previewCheckItemDraft = async () => {
    if (!sessionId || !configDraft || readOnly) return;
    const requestSeq = previewRequestSeq.current + 1;
    previewRequestSeq.current = requestSeq;
    setIsPreviewing(true);
    try {
      const payload = buildCheckItemPayload(configDraft);
      const result = await previewCheckItem({ session_id: sessionId, ...payload });
      if (previewRequestSeq.current === requestSeq) {
        setPreviewResult(result);
      }
    } catch (err) {
      if (previewRequestSeq.current === requestSeq) {
        window.alert(`用当前简报试审失败：${getErrorMessage(err)}`);
      }
    } finally {
      if (previewRequestSeq.current === requestSeq) {
        setIsPreviewing(false);
      }
    }
  };

  const handleSelectPreviewMatch = (match: RetrievalMatch) => {
    const anchors = getRetrievalMatchAnchors(match);
    setActiveEvidenceAnchors(anchors);
    const targetPage = getRetrievalMatchPage(match, anchors);
    if (targetPage) {
      setActiveDocumentPage(targetPage);
    }
  };

  const handleRunRetrievalDebug = async (query: string, options: RetrievalDebugOptions) => {
    if (!sessionId) return;
    setIsRetrievalDebugging(true);
    setRetrievalDebugError(null);
    try {
      const result = await runRetrievalDebug(sessionId, {
        query,
        ...options,
      });
      setRetrievalDebugResult(result);
    } catch (err) {
      setRetrievalDebugError(getErrorMessage(err));
    } finally {
      setIsRetrievalDebugging(false);
    }
  };

  const removeCheckItem = async (item: ReviewCheckItem) => {
    if (readOnly) return;
    if (!item.id || item.ai_or_human_source !== 'configured_checklist') return;
    const confirmed = window.confirm(`确认删除审查项「${item.review_sub_type}」吗？`);
    if (!confirmed) return;
    try {
      await deleteCheckItem(item.id);
      await refreshRuleTopics();
    } catch (err) {
      window.alert(`删除审查项失败：${getErrorMessage(err)}`);
    }
  };

  const handleOpenAction = (action: ActiveAction) => {
    if (readOnly) return;
    setActiveAction(action);
    setHumanNote('');
    setEditedFinding('');
    setIsFalsePositive(false);
    if (action === 'edit' && activeItem) {
      setEditedRiskLevel(activeItem.human_edited_risk_level ?? activeItem.risk_level);
    }
  };

  const handleSubmitDecision = async (decision: HumanDecision) => {
    if (!activeItem || !sessionId || readOnly) return;
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
    if (!sessionId || readOnly) return;
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
    <div className="h-screen overflow-x-auto overflow-y-hidden bg-slate-100 text-slate-800">
    <div className="flex h-full min-w-[1206px] flex-col overflow-hidden">
      <header className="flex h-[52px] shrink-0 items-center justify-between border-b border-slate-200 bg-white px-4">
        <div className="min-w-0">
          <h1 className="truncate text-[15px] font-semibold text-slate-900">水土保持方案智能审查系统</h1>
          <p className="mt-0.5 truncate text-[11px] text-slate-500">河北省水利厅 / 技术审查中心 / 项目审查工作台</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <StatusPill tone="blue">AI 审查完成 64 / 64</StatusPill>
          <StatusPill tone="amber">待专家确认 9</StatusPill>
          <StatusPill tone="green">解析页数 {documentContent?.page_count ?? '-'}</StatusPill>
          <button type="button" disabled={readOnly} className="rounded border border-slate-200 px-3 py-1.5 text-xs text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50">保存快照</button>
          <button type="button" disabled={readOnly} className="rounded bg-slate-900 px-3 py-1.5 text-xs text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300">生成审查意见稿</button>
        </div>
      </header>

      {readOnly && (
        <div className="shrink-0 border-b border-slate-200 bg-slate-50 px-4 py-2 text-xs text-slate-600">
          当前会话已中止，本页仅用于查看审查记录，不能提交、撤销或生成新的审查意见。
        </div>
      )}

      <ExtractedFieldsSummary sessionId={sessionId} dense className="shrink-0 rounded-none border-x-0 border-t-0 shadow-none" />

      <main className="grid min-h-0 flex-1 grid-cols-[232px_minmax(560px,1fr)_414px] overflow-hidden">
        <DocumentOutlinePanel
          documentContent={documentContent}
          activePage={activeDocumentPage}
          isLoading={isLoadingDocument}
          onSelectPage={setActiveDocumentPage}
        />
        <PdfWorkbenchPanel
          item={activeItem}
          evidenceRef={evidenceRef}
          documentContent={documentContent}
          activePage={activeDocumentPage}
          activeEvidenceAnchors={activeEvidenceAnchors}
          onSelectPage={setActiveDocumentPage}
          isLoading={isLoadingDocument}
        />
        <ReviewIssuePanel
          items={items}
          documentContent={documentContent}
          activeItemId={activeItemId}
          activeItem={activeItem}
          activeAction={activeAction}
          humanNote={humanNote}
          editedRiskLevel={editedRiskLevel}
          editedFinding={editedFinding}
          isFalsePositive={isFalsePositive}
          canApprove={canApprove}
          canEditSubmit={canEditSubmit}
          canRejectSubmit={canRejectSubmit}
          conditionA={conditionA}
          isLoadingItems={isLoadingItems}
          decidedCount={decidedCount}
          totalHigh={totalHigh}
          onSelectItem={handleSelectItem}
          onOpenAction={handleOpenAction}
          onNoteChange={setHumanNote}
          onEditLevelChange={setEditedRiskLevel}
          onEditFindingChange={setEditedFinding}
          onFalsePositiveChange={setIsFalsePositive}
          onConfirmDecision={(d) => {
            if (!readOnly) setConfirmModal({ decision: d });
          }}
          onRevoke={!readOnly && activeItem ? () => handleRevoke(activeItem.id) : undefined}
          onOpenCreateCheckItem={openCreateCheckItem}
          ruleTopicCount={ruleTopics.length}
          retrievalDebugResult={retrievalDebugResult}
          retrievalDebugError={retrievalDebugError}
          isRetrievalDebugging={isRetrievalDebugging}
          onRunRetrievalDebug={handleRunRetrievalDebug}
          onSelectRetrievalDebugMatch={handleSelectPreviewMatch}
        />
      </main>

      {configDraft && (
        <CheckItemDraftModal
          draft={configDraft}
          topic={draftRuleTopic}
          executorOptions={executorOptions}
          ruleOptions={draftRuleOptionsWithCurrent}
          executorBindingBlocked={executorBindingBlocked}
          isSaving={isSavingConfig}
          isPreviewing={isPreviewing}
          previewResult={previewResult}
          onChange={(nextDraft) => {
            resetPreviewState();
            setConfigDraft(nextDraft);
          }}
          onCancel={() => {
            resetPreviewState();
            setConfigDraft(null);
          }}
          onPreview={previewCheckItemDraft}
          onSave={saveCheckItemDraft}
        />
      )}

      {/* Confirmation Modal — R05: 不可通过 ESC/遮罩关闭 */}
      {confirmModal && activeItem && !readOnly && (
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
    </div>
  );
}

function StatusPill({ tone, children }: { tone: 'blue' | 'amber' | 'green'; children: React.ReactNode }) {
  const className = {
    blue: 'border-blue-200 bg-blue-50 text-blue-700',
    amber: 'border-amber-200 bg-amber-50 text-amber-700',
    green: 'border-emerald-200 bg-emerald-50 text-emerald-700',
  }[tone];
  return (
    <span className={`inline-flex h-7 items-center rounded-full border px-2.5 text-[11px] font-medium ${className}`}>
      {children}
    </span>
  );
}

function DocumentOutlinePanel({
  documentContent,
  activePage,
  isLoading,
  onSelectPage,
}: {
  documentContent: ReviewDocumentContentResponse | null;
  activePage: number;
  isLoading: boolean;
  onSelectPage: (page: number) => void;
}) {
  const outline = documentContent?.outline ?? [];
  const blockCount = documentContent?.pages.reduce((sum, page) => sum + page.blocks.length, 0) ?? 0;
  const materialRows = documentContent
    ? [
        `${documentContent.title}.${documentContent.file_type}`,
        `解析块 ${blockCount} 个`,
        `文档页数 ${documentContent.page_count} 页`,
      ]
    : ['解析内容加载中'];

  return (
    <aside className="flex min-h-0 flex-col border-r border-slate-200 bg-white">
      <div className="shrink-0 border-b border-slate-200 px-3 py-3">
        <h2 className="text-sm font-semibold text-slate-800">目录与材料</h2>
        <p className="mt-1 truncate text-[11px] text-slate-400">{documentContent?.title || '审查对象解析内容'}</p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 py-3">
        <SectionTitle label="文档目录" />
        {isLoading ? (
          <div className="flex items-center gap-2 px-2 py-5 text-[11px] text-slate-400">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> 加载解析大纲...
          </div>
        ) : outline.length === 0 ? (
          <div className="px-2 py-5 text-[11px] text-slate-400">未识别到标题大纲</div>
        ) : (
          <div className="space-y-0.5">
            {outline.map((item) => {
              const active = item.page_number === activePage;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => onSelectPage(item.page_number)}
                  className={`grid w-full grid-cols-[minmax(0,1fr)_42px] items-center gap-1 rounded py-1.5 pr-2 text-left text-[11px] ${
                    active ? 'bg-sky-50 text-sky-800 ring-1 ring-sky-200' : 'text-slate-600 hover:bg-slate-50'
                  }`}
                  style={{ paddingLeft: 8 + Math.max(0, item.level - 1) * 10 }}
                >
                  <span className="truncate" title={item.title}>{item.title}</span>
                  <span className="text-right text-slate-400">p.{item.page_number}</span>
                </button>
              );
            })}
          </div>
        )}

        <SectionTitle label="材料" className="mt-5" />
        <div className="space-y-1">
          {materialRows.map((item) => (
            <div key={item} className="flex items-center justify-between rounded px-2 py-1.5 text-[11px] text-slate-600 hover:bg-slate-50">
              <span className="truncate">{item}</span>
              <span className="ml-2 h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" />
            </div>
          ))}
        </div>

        <SectionTitle label="页码定位" className="mt-5" />
        <div className="grid grid-cols-4 gap-1 px-2">
          {(documentContent?.pages ?? []).slice(0, 40).map((page) => (
            <button
              key={page.page_number}
              type="button"
              onClick={() => onSelectPage(page.page_number)}
              className={`rounded px-1 py-1 text-[10px] ${
                page.page_number === activePage ? 'bg-slate-900 text-white' : 'bg-slate-50 text-slate-500 hover:bg-slate-100'
              }`}
            >
              {page.page_number}
            </button>
          ))}
        </div>
      </div>
    </aside>
  );
}

function SectionTitle({ label, className = '' }: { label: string; className?: string }) {
  return <p className={`mb-2 px-2 text-[11px] font-semibold text-slate-400 ${className}`}>{label}</p>;
}

function PdfWorkbenchPanel({
  item,
  evidenceRef,
  documentContent,
  activePage,
  activeEvidenceAnchors,
  onSelectPage,
  isLoading,
}: {
  item?: ReviewItem;
  evidenceRef: React.RefObject<HTMLDivElement | null>;
  documentContent: ReviewDocumentContentResponse | null;
  activePage: number;
  activeEvidenceAnchors: EvidenceAnchor[];
  onSelectPage: (page: number) => void;
  isLoading: boolean;
}) {
  const [viewerMode, setViewerMode] = useState<'pdf' | 'parsed'>('pdf');
  const page = documentContent?.pages.find((candidate) => candidate.page_number === activePage);
  const pageCount = documentContent?.page_count ?? 0;
  const title = documentContent?.title || '审查对象';
  const evidencePage = item?.clause_location?.page_number;
  const sourcePdfUrl = documentContent?.source_pdf_url || '';
  const activeViewerMode = sourcePdfUrl ? viewerMode : 'parsed';
  const pdfUrl = sourcePdfUrl ? pdfFrameUrl(sourcePdfUrl, activePage) : '';

  return (
    <section className="flex min-h-0 flex-col bg-slate-100">
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-slate-200 bg-white px-3">
        <div className="min-w-0">
          <p className="truncate text-xs font-semibold text-slate-800">{title}</p>
          <p className="mt-0.5 truncate text-[11px] text-slate-400">
            当前位置：第 {activePage} 页 / {activeViewerMode === 'pdf' ? '原始 PDF' : `解析来源：${documentContent?.source || 'parsed_blocks'}`}
          </p>
        </div>
        <div className="ml-3 flex shrink-0 items-center gap-1.5 text-[11px]">
          {sourcePdfUrl ? (
            <div className="mr-1 flex rounded border border-slate-200 bg-slate-50 p-0.5">
              <button
                type="button"
                onClick={() => setViewerMode('pdf')}
                className={`rounded px-2 py-0.5 ${activeViewerMode === 'pdf' ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-white'}`}
              >
                原始PDF
              </button>
              <button
                type="button"
                onClick={() => setViewerMode('parsed')}
                className={`rounded px-2 py-0.5 ${activeViewerMode === 'parsed' ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-white'}`}
              >
                解析证据
              </button>
            </div>
          ) : null}
          <button type="button" onClick={() => onSelectPage(Math.max(1, activePage - 1))} className="rounded border border-slate-200 px-2 py-1 text-slate-600 hover:bg-slate-50">上一页</button>
          <button type="button" onClick={() => onSelectPage(pageCount ? Math.min(pageCount, activePage + 1) : activePage + 1)} className="rounded border border-slate-200 px-2 py-1 text-slate-600 hover:bg-slate-50">下一页</button>
          <button
            type="button"
            onClick={() => evidencePage && onSelectPage(evidencePage)}
            disabled={!evidencePage}
            className="rounded border border-slate-200 px-2 py-1 text-slate-600 hover:bg-slate-50 disabled:text-slate-300"
          >
            跳转证据
          </button>
          <span className="rounded bg-slate-900 px-2 py-1 text-white">p.{activePage} / {pageCount || '-'}</span>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto bg-[#e5e7eb] px-8 py-5">
        {activeViewerMode === 'pdf' && pdfUrl ? (
          <div className="mx-auto h-full min-h-[760px] max-w-[980px] bg-white shadow-sm ring-1 ring-slate-300">
            <iframe
              key={pdfUrl}
              title={`${title} 原始PDF`}
              src={pdfUrl}
              className="h-[calc(100vh-190px)] min-h-[760px] w-full border-0 bg-white"
            />
          </div>
        ) : (
          <div
            ref={evidenceRef}
            className="relative mx-auto min-h-[920px] w-[680px] bg-white px-16 py-12 text-slate-800 shadow-sm ring-1 ring-slate-300"
          >
            {isLoading ? (
              <div className="flex h-[720px] items-center justify-center gap-2 text-xs text-slate-400">
                <Loader2 className="h-4 w-4 animate-spin" /> 加载审查对象解析内容...
              </div>
            ) : page ? (
              <DocumentPageView page={page} activeItem={item} activeEvidenceAnchors={activeEvidenceAnchors} title={title} />
            ) : (
              <div className="flex h-[720px] items-center justify-center text-xs text-slate-400">当前页暂无解析内容</div>
            )}
            {sourcePdfUrl ? (
              <div className="mt-6 rounded border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] leading-5 text-amber-800">
                当前为 MinerU 解析证据视图，用于 chunk、表格、图片和 bbox 定位；原始 PDF 视觉内容请切回“原始PDF”。
              </div>
            ) : null}
          </div>
        )}
      </div>
    </section>
  );
}

function pdfFrameUrl(path: string, page: number) {
  const url = resolveSessionFileUrl(path);
  if (!url) return '';
  const [base] = url.split('#');
  return `${base}#page=${Math.max(1, page)}&zoom=page-width`;
}

function resolveSessionFileUrl(path?: string) {
  const value = path?.trim();
  if (!value) return '';
  if (/^https?:\/\//i.test(value)) return value;
  try {
    return new URL(value, API_BASE_URL).toString();
  } catch {
    return value;
  }
}

function DocumentPageView({
  page,
  activeItem,
  activeEvidenceAnchors,
  title,
}: {
  page: ReviewDocumentPage;
  activeItem?: ReviewItem;
  activeEvidenceAnchors: EvidenceAnchor[];
  title: string;
}) {
  return (
    <>
      <div className="mb-7 flex items-start justify-between border-b border-slate-200 pb-3">
        <div className="min-w-0">
          <p className="truncate text-[13px] font-semibold">{title}</p>
          <p className="mt-1 text-[10px] text-slate-400">MinerU parsed_blocks · 第 {page.page_number} 页</p>
        </div>
        <p className="text-[10px] text-slate-400">{page.page_number}</p>
      </div>

      <div className="space-y-3 text-[12px] leading-6">
        {page.blocks.map((block) => (
          <DocumentBlockView
            key={block.block_id}
            block={block}
            highlighted={isActiveAnchorBlock(block, activeEvidenceAnchors) || isActiveEvidenceBlock(block, activeItem)}
          />
        ))}
      </div>
    </>
  );
}

function DocumentBlockView({ block, highlighted }: { block: ReviewDocumentBlock; highlighted: boolean }) {
  const hasRenderableMedia = Boolean(block.html || block.image_path);
  if (!block.text && !hasRenderableMedia) return null;
  const imageUrl = resolveDocumentAssetUrl(block.image_path);
  const baseClass = highlighted
    ? 'rounded-sm bg-red-100 px-1 text-red-900 ring-1 ring-red-200'
    : 'text-slate-800';

  if (block.type === 'title') {
    return (
      <h3 className={`text-[13px] font-semibold leading-6 ${highlighted ? baseClass : 'text-slate-900'}`}>
        {block.text}
      </h3>
    );
  }

  if (block.type === 'table') {
    const sanitizedHtml = block.html ? sanitizeDocumentHtml(block.html) : '';
    const hasVisibleHtml = htmlHasVisibleText(sanitizedHtml);
    return (
      <div className={`space-y-2 rounded border border-slate-200 bg-slate-50 px-2 py-2 text-[10px] leading-5 ${highlighted ? 'ring-1 ring-red-200' : ''}`}>
        {sanitizedHtml && hasVisibleHtml ? (
          <div
            className="overflow-x-auto [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-slate-200 [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:border-slate-200 [&_th]:bg-slate-100 [&_th]:px-2 [&_th]:py-1"
            dangerouslySetInnerHTML={{ __html: sanitizedHtml }}
          />
        ) : block.image_path ? null : (
          <div className="whitespace-pre-wrap font-mono text-slate-600">{block.text}</div>
        )}
        {block.image_path && !hasVisibleHtml ? (
          <img
            src={imageUrl}
            alt={block.text || 'MinerU table'}
            loading="lazy"
            className="max-h-[420px] w-full rounded border border-slate-200 bg-white object-contain"
          />
        ) : null}
      </div>
    );
  }

  if (block.type === 'image') {
    if (block.image_path) {
      return (
        <div className={`rounded border border-slate-200 bg-slate-50 p-2 ${highlighted ? 'ring-1 ring-red-200' : ''}`}>
          <img
            src={imageUrl}
            alt={block.text || 'MinerU image'}
            loading="lazy"
            className="max-h-[520px] w-full rounded bg-white object-contain"
          />
        </div>
      );
    }
    return (
      <div className="rounded border border-dashed border-slate-300 bg-slate-50 px-3 py-4 text-center text-[11px] text-slate-400">
        图像块：{truncateText(block.text, 80)}
      </div>
    );
  }

  return <p className={`whitespace-pre-wrap break-words ${baseClass}`}>{block.text}</p>;
}

function resolveDocumentAssetUrl(imagePath?: string) {
  const path = imagePath?.trim();
  if (!path) return '';
  if (/^https?:\/\//i.test(path)) return path;
  if (!path.startsWith('/api/v1/')) return path;
  try {
    return new URL(path, API_BASE_URL).toString();
  } catch {
    return path;
  }
}

function isActiveAnchorBlock(block: ReviewDocumentBlock, anchors: EvidenceAnchor[]): boolean {
  if (anchors.length === 0) return false;
  return anchors.some((anchor) => anchor.page === block.page && anchor.block_id === block.block_id);
}

function getRetrievalMatchAnchors(match: RetrievalMatch): EvidenceAnchor[] {
  return Array.isArray(match.anchors) ? match.anchors.filter((anchor) => typeof anchor.page === 'number') : [];
}

function getRetrievalMatchPage(match: RetrievalMatch, anchors = getRetrievalMatchAnchors(match)): number | null {
  const anchorPage = anchors.find((anchor) => typeof anchor.page === 'number')?.page;
  if (typeof anchorPage === 'number' && anchorPage > 0) return anchorPage;
  if (typeof match.primary_page === 'number' && match.primary_page > 0) return match.primary_page;
  if (typeof match.page === 'number' && match.page > 0) return match.page;
  return null;
}

function isActiveEvidenceBlock(block: ReviewDocumentBlock, activeItem?: ReviewItem): boolean {
  if (!activeItem || activeItem.clause_location.page_number !== block.page) return false;
  const evidenceText = activeItem.risk_evidence[0]?.evidence_text || activeItem.ai_finding || '';
  const needle = normalizeInlineText(evidenceText).slice(0, 28);
  if (!needle) return false;
  return normalizeInlineText(block.text).includes(needle);
}

function normalizeInlineText(value: string): string {
  return value.replace(/\s+/g, '');
}

function sanitizeDocumentHtml(html: string): string {
  return html
    .replace(/<script[\s\S]*?>[\s\S]*?<\/script>/gi, '')
    .replace(/<style[\s\S]*?>[\s\S]*?<\/style>/gi, '')
    .replace(/\son\w+="[^"]*"/gi, '')
    .replace(/\son\w+='[^']*'/gi, '')
    .replace(/javascript:/gi, '');
}

function htmlHasVisibleText(html: string): boolean {
  return html.replace(/<[^>]+>/g, ' ').replace(/&nbsp;/g, ' ').replace(/\s+/g, '').length > 0;
}

type WorkbenchIssueRow = {
  id: string;
  title: string;
  category: string;
  page: string;
  severity: RiskLevel;
  evidenceText: string;
  basisText: string;
  item?: ReviewItem;
  isStatic?: boolean;
};

type ChapterFilter = 'all' | 'current';
type SeverityFilter = 'all' | RiskLevel;
type RetrievalDebugOptions = {
  top_k: number;
  use_vector: boolean;
  use_bm25: boolean;
  use_neighbors: boolean;
  use_rerank: boolean;
  evidence_slot?: Record<string, unknown>;
};
type RetrievalContributionBadge = {
  key: string;
  label: string;
  className: string;
};
type DecisionFilter = 'pending' | 'handled' | 'all';

function ReviewIssuePanel({
  items,
  documentContent,
  activeItemId,
  activeItem,
  activeAction,
  humanNote,
  editedRiskLevel,
  editedFinding,
  isFalsePositive,
  canApprove,
  canEditSubmit,
  canRejectSubmit,
  conditionA,
  isLoadingItems,
  decidedCount,
  totalHigh,
  onSelectItem,
  onOpenAction,
  onNoteChange,
  onEditLevelChange,
  onEditFindingChange,
  onFalsePositiveChange,
  onConfirmDecision,
  onRevoke,
  onOpenCreateCheckItem,
  ruleTopicCount,
  retrievalDebugResult,
  retrievalDebugError,
  isRetrievalDebugging,
  onRunRetrievalDebug,
  onSelectRetrievalDebugMatch,
}: {
  items: ReviewItem[];
  documentContent: ReviewDocumentContentResponse | null;
  activeItemId: string | null;
  activeItem?: ReviewItem;
  activeAction: ActiveAction;
  humanNote: string;
  editedRiskLevel: RiskLevel;
  editedFinding: string;
  isFalsePositive: boolean;
  canApprove: boolean;
  canEditSubmit: boolean;
  canRejectSubmit: boolean;
  conditionA: boolean;
  isLoadingItems: boolean;
  decidedCount: number;
  totalHigh: number;
  onSelectItem: (itemId: string) => void;
  onOpenAction: (action: ActiveAction) => void;
  onNoteChange: (value: string) => void;
  onEditLevelChange: (value: RiskLevel) => void;
  onEditFindingChange: (value: string) => void;
  onFalsePositiveChange: (value: boolean) => void;
  onConfirmDecision: (decision: HumanDecision) => void;
  onRevoke?: () => void;
  onOpenCreateCheckItem: () => void;
  ruleTopicCount: number;
  retrievalDebugResult: RetrievalDebugResponse | null;
  retrievalDebugError: string | null;
  isRetrievalDebugging: boolean;
  onRunRetrievalDebug: (query: string, options: RetrievalDebugOptions) => void;
  onSelectRetrievalDebugMatch: (match: RetrievalMatch) => void;
}) {
  const [chapterFilter, setChapterFilter] = useState<ChapterFilter>('all');
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all');
  const [decisionFilter, setDecisionFilter] = useState<DecisionFilter>('pending');
  const rows = buildWorkbenchIssueRows(items, documentContent);
  const filteredRows = rows.filter((row) => {
    const matchesChapter = chapterFilter === 'all' || isCurrentSectionIssue(row);
    const matchesSeverity = severityFilter === 'all' || row.severity === severityFilter;
    const matchesDecision =
      decisionFilter === 'all' ||
      (decisionFilter === 'pending' ? getIssueDecision(row) === 'pending' : getIssueDecision(row) !== 'pending');
    return matchesChapter && matchesSeverity && matchesDecision;
  });
  const criticalRows = filteredRows.filter((row) => row.severity === 'HIGH');
  const normalRows = filteredRows.filter((row) => row.severity !== 'HIGH');
  const visibleActiveItem = filteredRows.some((row) => row.id === activeItemId && !row.isStatic) ? activeItem : undefined;
  const noteRemaining = Math.max(0, 10 - humanNote.trim().length);

  return (
    <aside className="flex min-h-0 flex-col border-l border-slate-200 bg-white">
      <div className="shrink-0 border-b border-slate-200 px-3 py-3">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-slate-800">审查问题</h2>
          <button type="button" onClick={onOpenCreateCheckItem} className="rounded border border-slate-200 px-2 py-1 text-[11px] text-slate-500 hover:bg-slate-50">
            新增规则
          </button>
        </div>
        <div className="mt-2 grid grid-cols-3 gap-1.5">
          <select
            value={chapterFilter}
            onChange={(event) => setChapterFilter(event.target.value as ChapterFilter)}
            className="min-w-0 rounded border border-slate-200 bg-white px-1.5 py-1 text-[11px] text-slate-600"
          >
            <option value="all">全部章节</option>
            <option value="current">当前章节</option>
          </select>
          <select
            value={severityFilter}
            onChange={(event) => setSeverityFilter(event.target.value as SeverityFilter)}
            className="min-w-0 rounded border border-slate-200 bg-white px-1.5 py-1 text-[11px] text-slate-600"
          >
            <option value="all">全部等级</option>
            <option value="HIGH">严重</option>
            <option value="MEDIUM">一般</option>
            <option value="LOW">提示</option>
          </select>
          <select
            value={decisionFilter}
            onChange={(event) => setDecisionFilter(event.target.value as DecisionFilter)}
            className="min-w-0 rounded border border-slate-200 bg-white px-1.5 py-1 text-[11px] text-slate-600"
          >
            <option value="pending">待确认</option>
            <option value="handled">已处理</option>
            <option value="all">全部状态</option>
          </select>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <RetrievalDebugPanel
          result={retrievalDebugResult}
          error={retrievalDebugError}
          isLoading={isRetrievalDebugging}
          onRun={onRunRetrievalDebug}
          onSelectMatch={onSelectRetrievalDebugMatch}
        />
        {isLoadingItems ? (
          <div className="flex items-center justify-center gap-2 px-4 py-10 text-xs text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" /> 加载审查问题中...
          </div>
        ) : (
          <>
            <IssueGroup title="重点问题" count={criticalRows.length}>
              {criticalRows.map((row) => (
                <IssueRow
                  key={row.id}
                  row={row}
                  active={activeItemId === row.id}
                  documentContent={documentContent}
                  onSelect={row.isStatic ? undefined : () => onSelectItem(row.id)}
                  onSelectEvidenceMatch={onSelectRetrievalDebugMatch}
                />
              ))}
            </IssueGroup>
            <IssueGroup title="一般核查" count={normalRows.length}>
              {normalRows.map((row) => (
                <IssueRow
                  key={row.id}
                  row={row}
                  active={activeItemId === row.id}
                  documentContent={documentContent}
                  onSelect={row.isStatic ? undefined : () => onSelectItem(row.id)}
                  onSelectEvidenceMatch={onSelectRetrievalDebugMatch}
                />
              ))}
            </IssueGroup>
            {filteredRows.length === 0 && (
              <div className="px-4 py-10 text-center text-xs text-slate-400">当前筛选条件下暂无审查问题</div>
            )}
          </>
        )}
      </div>

      <div className="shrink-0 border-t border-slate-200 bg-slate-50 px-3 py-3">
        <div className="mb-2 flex items-center justify-between text-[11px] text-slate-500">
          <span>人工处理</span>
          <span>高风险 {decidedCount}/{totalHigh} · 规则主题 {ruleTopicCount}</span>
        </div>
        {visibleActiveItem?.human_decision === 'pending' && (
          <div className="mt-2 space-y-2">
            {!activeAction && (
              <div className="flex gap-1.5">
                <button onClick={() => onOpenAction('approve')} className="rounded bg-emerald-600 px-2 py-1 text-[11px] text-white">确认</button>
                <button onClick={() => onOpenAction('edit')} className="rounded bg-amber-500 px-2 py-1 text-[11px] text-white">修正</button>
                <button onClick={() => onOpenAction('reject')} className="rounded bg-slate-600 px-2 py-1 text-[11px] text-white">驳回</button>
              </div>
            )}
            {activeAction === 'approve' && (
              <div className="space-y-2">
                <div className="text-[11px] text-slate-500">原文阅读：{conditionA ? '已确认' : '等待 2 秒阅读确认'}</div>
                <HumanNoteInput note={humanNote} onChange={onNoteChange} remaining={noteRemaining} />
                <ActionFooter disabled={!canApprove} label="提交确认" onSubmit={() => onConfirmDecision('approve')} onCancel={() => onOpenAction(null)} />
              </div>
            )}
            {activeAction === 'edit' && (
              <div className="space-y-2">
                <select value={editedRiskLevel} onChange={(e) => onEditLevelChange(e.target.value as RiskLevel)} className="w-full rounded border border-slate-200 px-2 py-1 text-xs">
                  <option value="HIGH">高风险</option>
                  <option value="MEDIUM">中风险</option>
                  <option value="LOW">低风险</option>
                </select>
                <textarea value={editedFinding} onChange={(e) => onEditFindingChange(e.target.value)} rows={2} className="w-full resize-none rounded border border-slate-200 px-2 py-1 text-xs" placeholder="修正后的审查结论" />
                <HumanNoteInput note={humanNote} onChange={onNoteChange} remaining={noteRemaining} />
                <ActionFooter disabled={!canEditSubmit} label="提交修正" onSubmit={() => onConfirmDecision('edit')} onCancel={() => onOpenAction(null)} />
              </div>
            )}
            {activeAction === 'reject' && (
              <div className="space-y-2">
                <label className="flex items-center gap-1.5 text-[11px] text-slate-600">
                  <input type="checkbox" checked={isFalsePositive} onChange={(e) => onFalsePositiveChange(e.target.checked)} />
                  标记为 AI 误报
                </label>
                <HumanNoteInput note={humanNote} onChange={onNoteChange} remaining={noteRemaining} />
                <ActionFooter disabled={!canRejectSubmit} label="提交驳回" onSubmit={() => onConfirmDecision('reject')} onCancel={() => onOpenAction(null)} />
              </div>
            )}
          </div>
        )}
        {!visibleActiveItem && (
          <p className="text-xs leading-5 text-slate-500">选择一条审查问题后，可在这里确认、修正或驳回。</p>
        )}
        {visibleActiveItem?.human_decision !== 'pending' && onRevoke && (
          <button onClick={onRevoke} className="mt-2 rounded border border-amber-200 px-2 py-1 text-[11px] text-amber-700 hover:bg-amber-50">
            撤销当前决策
          </button>
        )}
      </div>
    </aside>
  );
}

function ActionFooter({ disabled, label, onSubmit, onCancel }: { disabled: boolean; label: string; onSubmit: () => void; onCancel: () => void }) {
  return (
    <div className="flex items-center gap-2">
      <button disabled={disabled} onClick={onSubmit} className="rounded bg-slate-900 px-2.5 py-1 text-[11px] text-white disabled:bg-slate-300">
        {label}
      </button>
      <button onClick={onCancel} className="text-[11px] text-slate-500 hover:text-slate-700">取消</button>
    </div>
  );
}

function IssueGroup({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  return (
    <section className="border-b border-slate-100">
      <div className="flex items-center justify-between bg-slate-50 px-3 py-2">
        <p className="text-[11px] font-semibold text-slate-500">{title}</p>
        <span className="text-[11px] text-slate-400">{count}</span>
      </div>
      <div className="divide-y divide-slate-100">{children}</div>
    </section>
  );
}

function IssueRow({
  row,
  active,
  documentContent,
  onSelect,
  onSelectEvidenceMatch,
}: {
  row: WorkbenchIssueRow;
  active: boolean;
  documentContent: ReviewDocumentContentResponse | null;
  onSelect?: () => void;
  onSelectEvidenceMatch: (match: RetrievalMatch) => void;
}) {
  const disabled = !onSelect;
  return (
    <div
      className={`w-full px-3 py-2.5 text-left ${
        active ? 'bg-sky-50 shadow-[inset_3px_0_0_#0284c7]' : disabled ? 'bg-white opacity-85' : 'bg-white hover:bg-slate-50'
      }`}
    >
      <button
        type="button"
        onClick={onSelect}
        disabled={disabled}
        className={`w-full text-left ${disabled ? 'cursor-default' : ''}`}
      >
        <div className="flex items-start justify-between gap-2">
          <span className="min-w-0 text-xs font-medium leading-5 text-slate-800">{row.title}</span>
          <SeverityBadge level={row.severity} />
        </div>
        {row.evidenceText && (
          <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-600">
            原话：{row.evidenceText}
          </p>
        )}
        {row.basisText && (
          <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-500">
            逻辑：{row.basisText}
          </p>
        )}
        <div className="mt-1 flex items-center justify-between gap-2 text-[11px] text-slate-400">
          <span className="min-w-0 truncate">{row.category}</span>
          <span className="shrink-0">{row.page}</span>
        </div>
      </button>
      {row.item && (
        <ReviewResultSummaryPanel
          result={getIssueReviewResult(row.item, documentContent)}
          onSelectEvidenceMatch={onSelectEvidenceMatch}
        />
      )}
    </div>
  );
}

function ReviewResultSummaryPanel({
  result,
  onSelectEvidenceMatch,
}: {
  result: ReviewResult | null;
  onSelectEvidenceMatch: (match: RetrievalMatch) => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  if (!result) return null;
  const evidenceNodes = toRecordArray(result.evidence_nodes);
  const sourcePages = Array.isArray(result.source_pages) ? result.source_pages : [];
  const handleSelectEvidenceMatch = (match: RetrievalMatch) => {
    onSelectEvidenceMatch(match);
  };
  return (
    <div className="relative mt-2">
      <button
        type="button"
        onClick={() => setIsOpen((current) => !current)}
        className="w-full rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-left shadow-sm ring-1 ring-amber-100 hover:border-amber-400 hover:bg-amber-100"
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="text-[11px] font-semibold text-amber-800">AI 判断结论 / ReviewResult</p>
            <p className="mt-0.5 text-[10px] leading-4 text-amber-700">
              证据节点 {evidenceNodes.length} 个 · 页码 {sourcePages.join('、') || '-'} · 点击展开查看判断依据
            </p>
          </div>
          <span className="shrink-0 rounded bg-white/80 px-1.5 py-0.5 text-[10px] font-medium text-amber-700 ring-1 ring-amber-200">
            {isOpen ? '收起' : '展开'}
          </span>
        </div>
        <p className="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-700">
          {String(result.reasoning_summary || result.issue_desc || '-')}
        </p>
      </button>

      {isOpen && (
        <div className="fixed inset-0 z-50 bg-slate-900/10" onClick={() => setIsOpen(false)}>
          <div
            className="fixed right-[430px] top-[76px] w-[560px] max-w-[calc(100vw-456px)] overflow-hidden rounded-lg border border-amber-200 bg-white shadow-2xl ring-1 ring-black/10"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-3 border-b border-amber-100 bg-amber-50 px-4 py-3">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-slate-900">ReviewResult Schema</p>
                <p className="mt-1 text-[11px] leading-4 text-slate-600">
                  {String(result.review_topic || '-')} / {String(result.review_item || '-')}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="rounded p-1 text-slate-400 hover:bg-white hover:text-slate-700"
                aria-label="关闭 ReviewResult"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="max-h-[calc(100vh-148px)] space-y-3 overflow-y-auto px-4 py-3 text-xs leading-5 text-slate-700">
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 rounded border border-slate-100 bg-slate-50 px-3 py-2">
                <KeyValue label="issue_id" value={String(result.issue_id || '-')} />
                <KeyValue label="review_status" value={String(result.review_status || '-')} />
                <KeyValue label="rule_id" value={String(result.rule_id || '-')} />
                <KeyValue label="risk_level" value={String(result.risk_level || '-')} />
                <KeyValue label="rule_name" value={String(result.rule_name || '-')} />
                <KeyValue label="confidence" value={String(result.confidence ?? '-')} />
                <KeyValue label="source_pages" value={sourcePages.join('、') || '-'} />
                <KeyValue label="bbox_count" value={String(toRecordArray(result.source_bbox_list).length)} />
              </div>

              <div className="rounded border border-slate-100 px-3 py-2">
                <p className="font-semibold text-slate-800">问题描述</p>
                <p className="mt-1 text-slate-600">{String(result.issue_desc || '-')}</p>
              </div>

              <div className="rounded border border-sky-100 bg-sky-50/70 px-3 py-2">
                <p className="font-semibold text-sky-800">推理关键文案</p>
                <p className="mt-1 text-slate-700">{String(result.reasoning_summary || '-')}</p>
              </div>

              <div className="rounded border border-emerald-100 bg-emerald-50/70 px-3 py-2">
                <p className="font-semibold text-emerald-800">修改建议</p>
                <p className="mt-1 text-slate-700">{String(result.fix_suggestion || '-')}</p>
              </div>

              <div className="rounded border border-slate-100 px-3 py-2">
                <p className="font-semibold text-slate-800">证据文本</p>
                <p className="mt-1 whitespace-pre-wrap text-slate-600">{String(result.evidence_text || '-')}</p>
              </div>

              <div>
                <div className="mb-1 flex items-center justify-between gap-2">
                  <p className="font-semibold text-slate-800">可点击证据节点</p>
                  <span className="text-[11px] text-slate-400">{evidenceNodes.length} 个</span>
                </div>
                <div className="space-y-1.5">
                  {evidenceNodes.map((node, index) => {
                    const match = reviewResultNodeToRetrievalMatch(node);
                    return (
                      <button
                        key={`${String(node.chunk_id || index)}`}
                        type="button"
                        onClick={() => handleSelectEvidenceMatch(match)}
                        className="w-full rounded border border-slate-100 bg-slate-50 px-2.5 py-2 text-left text-[11px] leading-4 text-slate-700 hover:border-sky-200 hover:bg-sky-50 hover:text-sky-800"
                      >
                        <span className="block font-semibold">
                          节点 {index + 1} · {String(match.chunk_id || '-')} · p.{String(match.page || match.primary_page || '-')} · bbox {String(match.bbox_count ?? '-')}
                        </span>
                        <span className="mt-0.5 line-clamp-2 block">{String(match.text || '')}</span>
                      </button>
                    );
                  })}
                  {evidenceNodes.length === 0 && (
                    <p className="rounded bg-slate-50 px-2 py-2 text-[11px] text-slate-400">暂无可定位证据节点</p>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function reviewResultNodeToRetrievalMatch(node: Record<string, unknown>): RetrievalMatch {
  const page = Number(node.page || node.primary_page || 0);
  const pageEnd = Number(node.page_end || page || 0);
  const anchors = toRecordArray(node.anchors)
    .map((anchor) => ({
      page: Number(anchor.page || page || 0),
      block_id: typeof anchor.block_id === 'string' ? anchor.block_id : undefined,
      bbox: Array.isArray(anchor.bbox) ? anchor.bbox as number[] : undefined,
      coordinate_mode: typeof anchor.coordinate_mode === 'string' ? anchor.coordinate_mode : undefined,
      page_width: typeof anchor.page_width === 'number' ? anchor.page_width : null,
      page_height: typeof anchor.page_height === 'number' ? anchor.page_height : null,
    }))
    .filter((anchor) => anchor.page > 0);
  return {
    chunk_id: String(node.chunk_id || ''),
    page: page > 0 ? page : undefined,
    page_end: pageEnd > 0 ? pageEnd : undefined,
    primary_page: page > 0 ? page : undefined,
    page_range: page > 0 && pageEnd > 0 ? [page, pageEnd] : [],
    section: typeof node.section === 'string' ? node.section : undefined,
    anchors,
    block_ids: toStringArray(node.block_ids),
    bbox_count: typeof node.bbox_count === 'number' ? node.bbox_count : anchors.length,
    retrieval_sources: toStringArray(node.retrieval_sources),
    text: String(node.text || ''),
  };
}

function ReviewResultDetailPanel({ result }: { result: ReviewResult }) {
  const evidenceNodes = toRecordArray(result.evidence_nodes);
  return (
    <div className="rounded-lg border border-indigo-100 bg-indigo-50/60 px-3 py-2 text-xs space-y-1">
      <p className="text-indigo-700" style={{ fontWeight: 600 }}>ReviewResult Schema</p>
      <KeyValue label="issue_id" value={String(result.issue_id || '-')} />
      <KeyValue label="review_topic" value={String(result.review_topic || '-')} />
      <KeyValue label="review_item" value={String(result.review_item || '-')} />
      <KeyValue label="rule_id / rule_name" value={`${String(result.rule_id || '-')} / ${String(result.rule_name || '-')}`} />
      <KeyValue label="risk_level / confidence" value={`${String(result.risk_level || '-')} / ${String(result.confidence ?? '-')}`} />
      <KeyValue label="review_status" value={String(result.review_status || '-')} />
      <KeyValue label="source_pages" value={(result.source_pages || []).join('、') || '-'} />
      <KeyValue label="reasoning_summary" value={String(result.reasoning_summary || '-')} />
      <KeyValue label="fix_suggestion" value={String(result.fix_suggestion || '-')} />
      <div className="mt-1 space-y-1">
        {evidenceNodes.slice(0, 5).map((node, index) => (
          <div key={`${String(node.chunk_id || index)}`} className="rounded bg-white px-2 py-1 text-[11px] text-slate-600 ring-1 ring-indigo-100">
            <p className="font-medium text-slate-700">{index + 1}. {String(node.chunk_id || '-')} · p.{String(node.page || '-')} · bbox {String(node.bbox_count ?? '-')}</p>
            <p className="line-clamp-2">{String(node.text || '')}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function SeverityBadge({ level }: { level: RiskLevel }) {
  const config = {
    HIGH: 'border-red-200 bg-red-50 text-red-700',
    MEDIUM: 'border-amber-200 bg-amber-50 text-amber-700',
    LOW: 'border-slate-200 bg-slate-50 text-slate-600',
  }[level];
  const label = { HIGH: '严重', MEDIUM: '一般', LOW: '提示' }[level];
  return <span className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] ${config}`}>{label}</span>;
}

function buildWorkbenchIssueRows(items: ReviewItem[], documentContent?: ReviewDocumentContentResponse | null): WorkbenchIssueRow[] {
  if (items.length > 0) {
    return items.map((item, index) => ({
      id: item.id,
      title: truncateText(getIssueDisplayTitle(item, documentContent) || `审查问题 ${index + 1}`, 112),
      category: item.risk_category || '水土保持措施审查',
      page: `p.${item.clause_location?.page_number ?? 126}`,
      severity: item.risk_level,
      evidenceText: truncateText(getIssueEvidenceQuote(item, documentContent), 108),
      basisText: truncateText(getIssueBasisSummary(item, documentContent), 118),
      item,
    }));
  }

  const fallback: WorkbenchIssueRow[] = [
    { id: 'static-issue-1', title: '弃渣场安全距离和稳定性复核缺失', category: '6.2 弃渣场选址及防护设计', page: 'p.126', severity: 'HIGH', evidenceText: '', basisText: '', isStatic: true },
    { id: 'static-issue-2', title: '截排水断面尺寸未与附图保持一致', category: '附图 T2 / 排水沟断面', page: 'p.128', severity: 'HIGH', evidenceText: '', basisText: '', isStatic: true },
    { id: 'static-issue-3', title: '临时苫盖材料规格和维护频次说明不足', category: '施工期临时防护', page: 'p.134', severity: 'MEDIUM', evidenceText: '', basisText: '', isStatic: true },
    { id: 'static-issue-4', title: '监测点位布设缺少弃渣区覆盖', category: '水土保持监测', page: 'p.211', severity: 'MEDIUM', evidenceText: '', basisText: '', isStatic: true },
    { id: 'static-issue-5', title: '建议补充施工前后影像归档要求', category: '资料归档', page: 'p.236', severity: 'LOW', evidenceText: '', basisText: '', isStatic: true },
  ];
  return fallback;
}

function isCurrentSectionIssue(row: WorkbenchIssueRow): boolean {
  if (row.page === 'p.126' || row.page === 'p.128') return true;
  return row.category.includes('6.2') || row.category.includes('弃渣场');
}

function getIssueDecision(row: WorkbenchIssueRow): HumanDecision {
  return row.item?.human_decision ?? 'pending';
}

function getIssueDisplayTitle(item?: ReviewItem, documentContent?: ReviewDocumentContentResponse | null): string {
  if (!item) return '';
  const reviewResult = getIssueReviewResult(item, documentContent);
  if (reviewResult?.issue_desc) return String(reviewResult.issue_desc);
  const rawFinding = String(item.ai_finding || '').trim();
  const reasoning = parseReasoning(item.ai_reasoning) ?? {};
  const explicitSteps = toStringArray(reasoning.judgement_steps);
  const explicitBasis = String(reasoning.judgement_basis || '').trim();
  const actualValue = String(reasoning.actual_value || '').trim();
  const expectedValue = String(reasoning.expected_value || reasoning.evidence_requirement || '').trim();
  const ruleName = String(reasoning.rule_name || item.risk_category || '').trim();
  const findingIsGeneric = rawFinding.includes('部分目标字段或证据材料需要复核');

  if (explicitBasis && explicitSteps.length > 0) {
    return [
      ruleName || rawFinding,
      explicitSteps.slice(0, 3).join('；'),
      `判定依据：${explicitBasis}`,
    ].filter(Boolean).join('：');
  }

  if (findingIsGeneric && (actualValue || expectedValue)) {
    return [
      ruleName || rawFinding.replace('：部分目标字段或证据材料需要复核。', ''),
      actualValue,
      expectedValue ? `规则要求：${expectedValue}` : '',
      '结论：存在待核验字段或证据材料，暂不能判定通过',
    ].filter(Boolean).join('；');
  }

  return rawFinding;
}

function getIssueReviewResult(item?: ReviewItem, documentContent?: ReviewDocumentContentResponse | null): ReviewResult | null {
  if (!item) return null;
  const reasoning = parseReasoning(item.ai_reasoning) ?? {};
  const base = (item.review_result ?? reasoning.review_result ?? null) as ReviewResult | null;
  const synthetic = buildReviewResultFromDocument(item, reasoning, documentContent);
  if (!base) return synthetic;
  if (!synthetic) return base;
  const baseNodeCount = Array.isArray(base.evidence_nodes) ? base.evidence_nodes.length : 0;
  const syntheticNodeCount = Array.isArray(synthetic.evidence_nodes) ? synthetic.evidence_nodes.length : 0;
  if (syntheticNodeCount > baseNodeCount) {
    return {
      ...base,
      evidence_text: synthetic.evidence_text || base.evidence_text,
      evidence_nodes: synthetic.evidence_nodes,
      source_pages: synthetic.source_pages,
      source_bbox_list: synthetic.source_bbox_list,
      reasoning_summary: base.reasoning_summary || synthetic.reasoning_summary,
    };
  }
  return base;
}

function buildReviewResultFromDocument(
  item: ReviewItem,
  reasoning: Record<string, any>,
  documentContent?: ReviewDocumentContentResponse | null,
): ReviewResult | null {
  const keywords = getReviewResultKeywords(reasoning);
  if (!documentContent || keywords.length === 0) return null;
  const nodes: Array<Record<string, unknown> & { _score?: number; _order?: number }> = [];
  let order = 0;
  for (const page of documentContent.pages) {
    for (const block of page.blocks) {
      const text = String(block.text || '').trim();
      if (!text) continue;
      const matchedTerms = keywords.filter((keyword) => text.includes(keyword));
      if (matchedTerms.length === 0) continue;
      nodes.push({
        chunk_id: block.block_id,
        page: block.page || page.page_number,
        page_end: block.page || page.page_number,
        section: block.section_hint,
        block_ids: [block.block_id],
        bbox_count: block.bbox?.length ? 1 : 0,
        matched_terms: matchedTerms,
        retrieval_sources: ['document_keyword'],
        text,
        anchors: [{
          page: block.page || page.page_number,
          block_id: block.block_id,
          bbox: block.bbox,
          coordinate_mode: 'page_coordinate',
        }],
        _score: matchedTerms.length,
        _order: order,
      });
      order += 1;
    }
  }
  const selected = nodes
    .sort((a, b) => Number(b._score || 0) - Number(a._score || 0) || Number(a._order || 0) - Number(b._order || 0))
    .slice(0, 6)
    .map(({ _score, _order, ...node }) => node);
  if (selected.length === 0) return null;
  const sourcePages = Array.from(new Set(selected.map((node) => Number(node.page)).filter((page) => Number.isFinite(page) && page > 0))).sort((a, b) => a - b);
  const sourceBboxList = selected.flatMap((node) => toRecordArray(node.anchors));
  return {
    issue_id: item.id,
    review_topic: item.risk_category,
    review_item: String(reasoning.rule_name || item.risk_category || ''),
    rule_id: String(reasoning.rule_id || ''),
    rule_name: String(reasoning.rule_name || ''),
    risk_level: item.risk_level,
    issue_desc: buildIssueDescFromReasoning(item, reasoning),
    evidence_text: selected.map((node, index) => `${index + 1}. ${String(node.chunk_id || '-')} p.${String(node.page || '-')}：${truncateText(node.text, 240)}`).join('\n'),
    evidence_nodes: selected,
    source_pages: sourcePages,
    source_bbox_list: sourceBboxList,
    reasoning_summary: buildReasoningSummaryFromReasoning(reasoning, item),
    fix_suggestion: item.suggested_revision || '补齐证据后重新审查。',
    confidence: item.confidence_score,
    review_status: item.human_decision === 'pending' ? '待审核' : item.human_decision === 'approve' ? '已确认' : '已关闭',
  };
}

function getReviewResultKeywords(reasoning: Record<string, any>): string[] {
  const matchedFields = toStringArray(reasoning.matched_target_fields);
  if (matchedFields.length > 0) return matchedFields;
  const actual = String(reasoning.actual_value || '');
  const matchedPart = actual.match(/已命中[:：]([^；;]+)/)?.[1] || '';
  const parsed = matchedPart.split(/[、,，]/).map((item) => item.trim()).filter(Boolean);
  if (parsed.length > 0) return parsed;
  return toStringArray(reasoning.target_fields).slice(0, 6);
}

function buildIssueDescFromReasoning(item: ReviewItem, reasoning: Record<string, any>): string {
  const rawFinding = String(item.ai_finding || '').trim();
  const actualValue = String(reasoning.actual_value || '').trim();
  const expectedValue = String(reasoning.expected_value || reasoning.evidence_requirement || '').trim();
  const ruleName = String(reasoning.rule_name || item.risk_category || '').trim();
  if (rawFinding.includes('部分目标字段或证据材料需要复核') && (actualValue || expectedValue)) {
    return [
      ruleName || rawFinding.replace('：部分目标字段或证据材料需要复核。', ''),
      actualValue,
      expectedValue ? `规则要求：${expectedValue}` : '',
      '结论：存在待核验字段或证据材料，暂不能判定通过',
    ].filter(Boolean).join('；');
  }
  return rawFinding;
}

function buildReasoningSummaryFromReasoning(reasoning: Record<string, any>, item: ReviewItem): string {
  const explicit = String(reasoning.reasoning_summary || '').trim();
  if (explicit) return explicit;
  const steps = toStringArray(reasoning.judgement_steps);
  if (steps.length > 0) return steps.slice(0, 6).join('；');
  return [
    `判定对象：${String(reasoning.rule_name || item.risk_category || '')}`,
    String(reasoning.actual_value || '') ? `实际命中：${String(reasoning.actual_value)}` : '',
    String(reasoning.expected_value || '') ? `规则要求：${String(reasoning.expected_value)}` : '',
    '判定结论：存在待核验字段或证据材料时，不判定通过。',
  ].filter(Boolean).join('；');
}

function getReviewItemEvidenceAnchors(item?: ReviewItem, documentContent?: ReviewDocumentContentResponse | null): EvidenceAnchor[] {
  if (!item) return [];
  const reasoning = parseReasoning(item.ai_reasoning) ?? {};
  const anchors: EvidenceAnchor[] = [];

  collectAnchorsFromValue(item.review_result, anchors);
  collectAnchorsFromValue(reasoning.review_result, anchors);
  collectAnchorsFromValue(getIssueReviewResult(item, documentContent), anchors);
  collectAnchorsFromValue(reasoning.source_bbox_list, anchors);
  collectAnchorsFromValue(item.project_composition_consistency, anchors);
  collectAnchorsFromValue(reasoning.project_composition_consistency, anchors);
  collectAnchorsFromValue(item.evidence_slot_package, anchors);
  collectAnchorsFromValue(reasoning.evidence_slot_package, anchors);

  return dedupeEvidenceAnchors(anchors);
}

function collectAnchorsFromValue(value: unknown, target: EvidenceAnchor[]) {
  if (!value) return;
  if (Array.isArray(value)) {
    value.forEach((item) => {
      if (isEvidenceAnchorRecord(item)) target.push(toEvidenceAnchor(item));
      else collectAnchorsFromValue(item, target);
    });
    return;
  }
  if (typeof value !== 'object') return;
  const record = value as Record<string, unknown>;
  if (isEvidenceAnchorRecord(record)) {
    target.push(toEvidenceAnchor(record));
  }
  ['anchors', 'source_bbox_list', 'bbox_list'].forEach((key) => collectAnchorsFromValue(record[key], target));
  ['body_source', 'reference_source'].forEach((key) => collectAnchorsFromValue(record[key], target));
  ['slots', 'matches', 'prompt_matches', 'trace_matches', 'retrieval_matches', 'evidence_nodes'].forEach((key) => collectAnchorsFromValue(record[key], target));
}

function isEvidenceAnchorRecord(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  return typeof record.page === 'number' && (typeof record.block_id === 'string' || Array.isArray(record.bbox));
}

function toEvidenceAnchor(record: Record<string, unknown>): EvidenceAnchor {
  return {
    page: typeof record.page === 'number' ? record.page : undefined,
    block_id: typeof record.block_id === 'string' ? record.block_id : undefined,
    bbox: Array.isArray(record.bbox) ? record.bbox as number[] : undefined,
    coordinate_mode: typeof record.coordinate_mode === 'string' ? record.coordinate_mode : undefined,
    page_width: typeof record.page_width === 'number' ? record.page_width : null,
    page_height: typeof record.page_height === 'number' ? record.page_height : null,
  };
}

function dedupeEvidenceAnchors(anchors: EvidenceAnchor[]): EvidenceAnchor[] {
  const seen = new Set<string>();
  const result: EvidenceAnchor[] = [];
  anchors.forEach((anchor) => {
    if (typeof anchor.page !== 'number' || !anchor.block_id) return;
    const key = `${anchor.page}:${anchor.block_id}:${JSON.stringify(anchor.bbox ?? [])}`;
    if (seen.has(key)) return;
    seen.add(key);
    result.push(anchor);
  });
  return result;
}

function getIssueEvidenceQuote(item?: ReviewItem, documentContent?: ReviewDocumentContentResponse | null): string {
  if (!item) return '';
  const reviewResult = getIssueReviewResult(item, documentContent);
  const reviewEvidence = String(reviewResult?.evidence_text || '').trim();
  if (reviewEvidence) return reviewEvidence;
  const primaryEvidence = item.risk_evidence.find((ev) => ev.is_primary)?.evidence_text || item.risk_evidence[0]?.evidence_text;
  if (primaryEvidence?.trim()) return primaryEvidence.trim();
  const reasoning = parseReasoning(item.ai_reasoning) ?? {};
  const projectComposition = item.project_composition_consistency ?? reasoning.project_composition_consistency;
  const quotes = projectComposition && typeof projectComposition === 'object'
    ? (projectComposition as Record<string, unknown>).evidence_quotes
    : null;
  if (quotes && typeof quotes === 'object') {
    const body = String((quotes as Record<string, unknown>).body || '').trim();
    const reference = String((quotes as Record<string, unknown>).reference || '').trim();
    return [body, reference].filter(Boolean).join('；');
  }
  const firstMatch = firstRetrievalMatchText(item.evidence_slot_package ?? reasoning.evidence_slot_package);
  return firstMatch || '';
}

function firstRetrievalMatchText(value: unknown): string {
  if (!value) return '';
  if (Array.isArray(value)) {
    for (const item of value) {
      const text = firstRetrievalMatchText(item);
      if (text) return text;
    }
    return '';
  }
  if (typeof value !== 'object') return '';
  const record = value as Record<string, unknown>;
  if (typeof record.text === 'string' && record.text.trim()) return record.text.trim();
  for (const key of ['prompt_matches', 'matches', 'trace_matches', 'slots']) {
    const text = firstRetrievalMatchText(record[key]);
    if (text) return text;
  }
  return '';
}

function getIssueBasisSummary(item?: ReviewItem, documentContent?: ReviewDocumentContentResponse | null): string {
  if (!item) return '';
  const reviewResult = getIssueReviewResult(item, documentContent);
  const reviewSummary = String(reviewResult?.reasoning_summary || '').trim();
  if (reviewSummary) return reviewSummary;
  const reasoning = parseReasoning(item.ai_reasoning) ?? {};
  const explicitBasis = String(reasoning.judgement_basis || '').trim();
  const explicitSteps = toStringArray(reasoning.judgement_steps);
  if (explicitBasis || explicitSteps.length > 0) {
    return [explicitSteps.slice(0, 2).join('；'), explicitBasis].filter(Boolean).join('；');
  }
  const actualValue = String(reasoning.actual_value || '').trim();
  const expectedValue = String(reasoning.expected_value || reasoning.evidence_requirement || '').trim();
  if (actualValue || expectedValue) {
    return [
      actualValue ? `判定过程：${actualValue}` : '',
      expectedValue ? `规则依据：${expectedValue}` : '',
      '存在待核验字段时不判定通过',
    ].filter(Boolean).join('；');
  }
  const projectComposition = item.project_composition_consistency ?? reasoning.project_composition_consistency;
  if (projectComposition && typeof projectComposition === 'object') {
    const record = projectComposition as Record<string, unknown>;
    const findings = toStringArray(record.key_findings);
    const basis = String(record.judgement_basis || '').trim();
    const reason = String(record.reason || '').trim();
    return [findings.slice(0, 2).join('；'), basis || reason].filter(Boolean).join('；');
  }
  const formulaResults = item.formula_check_results ?? reasoning.formula_check_results;
  if (formulaResults && typeof formulaResults === 'object') {
    const checks = toRecordArray((formulaResults as Record<string, unknown>).checks);
    const firstIssue = checks.find((check) => ['fail', 'missing', 'unsupported'].includes(String(check.status || '')));
    if (firstIssue) {
      return `公式 ${String(firstIssue.formula_check_id || firstIssue.label || '-')}：${String(firstIssue.status || '-')}，${String(firstIssue.failure_reason || '')}`;
    }
  }
  const slotPackage = item.evidence_slot_package ?? reasoning.evidence_slot_package;
  if (slotPackage && typeof slotPackage === 'object') {
    const missing = toStringArray((slotPackage as Record<string, unknown>).missing_required_slot_ids);
    if (missing.length > 0) return `缺失必填证据槽位：${missing.join('、')}`;
  }
  return [String(reasoning.rule_name || ''), String(reasoning.expected_value || '')].filter(Boolean).join('；');
}

function RetrievalDebugPanel({
  result,
  error,
  isLoading,
  onRun,
  onSelectMatch,
}: {
  result: RetrievalDebugResponse | null;
  error: string | null;
  isLoading: boolean;
  onRun: (query: string, options: RetrievalDebugOptions) => void;
  onSelectMatch: (match: RetrievalMatch) => void;
}) {
  const [query, setQuery] = useState('弃渣场 480m 截排水');
  const [topK, setTopK] = useState(50);
  const [useVector, setUseVector] = useState(true);
  const [useBm25, setUseBm25] = useState(true);
  const [useNeighbors, setUseNeighbors] = useState(true);
  const [useRerank, setUseRerank] = useState(true);
  const [debugMode, setDebugMode] = useState<'query' | 'slot'>('query');
  const [slotId, setSlotId] = useState('debug_slot');
  const [minMatches, setMinMatches] = useState(1);
  const [expectedTerms, setExpectedTerms] = useState('');
  const canRun = query.trim().length > 0 && !isLoading && (useVector || useBm25);
  const matches = result?.matches ?? [];
  const retrievalDefaults = (result?.trace.retrieval_defaults || result?.trace.evidence_slot_defaults || {}) as Record<string, unknown>;
  const statusClass = result?.status === 'ready'
    ? 'bg-emerald-50 text-emerald-700'
    : result?.status === 'degraded'
      ? 'bg-amber-50 text-amber-700'
      : 'bg-slate-50 text-slate-500';

  return (
    <section className="border-b border-slate-100 bg-white px-3 py-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-[11px] font-semibold text-slate-500">Retrieval Debug</p>
        <span className={`rounded px-1.5 py-0.5 text-[10px] ${statusClass}`}>
          {result?.status ?? 'idle'}
        </span>
      </div>
      <form
        className="flex gap-1.5"
        onSubmit={(event) => {
          event.preventDefault();
          if (canRun) {
            onRun(query.trim(), {
              top_k: topK,
              use_vector: useVector,
              use_bm25: useBm25,
              use_neighbors: useNeighbors,
              use_rerank: useRerank,
              evidence_slot: debugMode === 'slot'
                ? {
                    id: slotId.trim() || 'debug_slot',
                    label: slotId.trim() || 'debug_slot',
                    required: true,
                    queries: [query.trim()],
                    expected_terms: parseListInput(expectedTerms),
                    min_matches: minMatches,
                  }
                : undefined,
            });
          }
        }}
      >
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="min-w-0 flex-1 rounded border border-slate-200 px-2 py-1 text-[11px] text-slate-700 outline-none focus:border-blue-300"
          placeholder="输入检索 query"
        />
        <button
          type="submit"
          disabled={!canRun}
          className="inline-flex shrink-0 items-center gap-1 rounded bg-slate-900 px-2 py-1 text-[11px] text-white disabled:bg-slate-300"
        >
          {isLoading && <Loader2 className="h-3 w-3 animate-spin" />}
          查询
        </button>
      </form>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-[10px] text-slate-500">
        <label className="inline-flex items-center gap-1">
          <input
            type="checkbox"
            checked={debugMode === 'slot'}
            onChange={(event) => setDebugMode(event.target.checked ? 'slot' : 'query')}
          />
          slot
        </label>
        <label className="inline-flex items-center gap-1">
          top_k
          <input
            type="number"
            min={1}
            max={50}
            value={topK}
            onChange={(event) => setTopK(Number(event.target.value) || 1)}
            className="h-6 w-12 rounded border border-slate-200 px-1 text-[10px] outline-none focus:border-blue-300"
          />
        </label>
        <label className="inline-flex items-center gap-1">
          <input type="checkbox" checked={useVector} onChange={(event) => setUseVector(event.target.checked)} />
          vector
        </label>
        <label className="inline-flex items-center gap-1">
          <input type="checkbox" checked={useBm25} onChange={(event) => setUseBm25(event.target.checked)} />
          BM25
        </label>
        <label className="inline-flex items-center gap-1">
          <input type="checkbox" checked={useNeighbors} onChange={(event) => setUseNeighbors(event.target.checked)} />
          neighbor
        </label>
        <label className="inline-flex items-center gap-1">
          <input type="checkbox" checked={useRerank} onChange={(event) => setUseRerank(event.target.checked)} />
          rerank
        </label>
      </div>
      {debugMode === 'slot' && (
        <div className="mt-2 grid grid-cols-[minmax(0,1fr)_56px] gap-1.5 text-[10px] text-slate-500">
          <input
            value={slotId}
            onChange={(event) => setSlotId(event.target.value)}
            className="h-7 rounded border border-slate-200 px-2 text-[10px] outline-none focus:border-blue-300"
            placeholder="slot_id"
          />
          <input
            type="number"
            min={1}
            value={minMatches}
            onChange={(event) => setMinMatches(Math.max(1, Number(event.target.value) || 1))}
            className="h-7 rounded border border-slate-200 px-1 text-[10px] outline-none focus:border-blue-300"
            title="min_matches"
          />
          <input
            value={expectedTerms}
            onChange={(event) => setExpectedTerms(event.target.value)}
            className="col-span-2 h-7 rounded border border-slate-200 px-2 text-[10px] outline-none focus:border-blue-300"
            placeholder="expected_terms，用逗号或换行分隔"
          />
        </div>
      )}
      {error && <p className="mt-2 text-[11px] leading-4 text-red-600">{error}</p>}
      {result && (
        <div className="mt-2 space-y-1 text-[10px] leading-4 text-slate-400">
          <p>
            {String(result.trace.debug_mode || 'query')} · {result.trace.retrieval_mode || '-'} · chunks {result.trace.chunk_count ?? '-'} · vector {result.trace.vector_available ? 'on' : 'off'} · BM25 {result.trace.bm25_available ? 'on' : 'off'} · rerank {result.trace.rerank_available ? 'on' : 'off'}
          </p>
          <p>
            request: vector {result.trace.requested_use_vector ? 'on' : 'off'} · BM25 {result.trace.requested_use_bm25 ? 'on' : 'off'} · neighbor {result.trace.requested_use_neighbors ? 'on' : 'off'} · rerank {result.trace.requested_use_rerank ? 'on' : 'off'}
          </p>
          <p>
            defaults: candidate {String(retrievalDefaults.candidate_top_k ?? '-')} · rerank candidates {String(retrievalDefaults.rerank_candidate_top_n ?? '-')} · final/slot {String(retrievalDefaults.final_top_k_per_slot ?? '-')}
          </p>
          {result.trace.top_k_clamped && (
            <p className="text-amber-600">top_k 已从 {result.trace.requested_top_k} 裁剪为 {result.trace.top_k}</p>
          )}
          {result.status === 'degraded' && (
            <p className="text-amber-600">当前为降级检索，仅使用可用检索路径。</p>
          )}
          {result.status === 'unavailable' && (
            <p className="text-red-600">检索不可用：{result.reason || 'artifact 不完整'}</p>
          )}
        </div>
      )}
      {result?.evidence_slot_package && (
        <div className="mt-2">
          <EvidenceSlotPackagePanel
            packageData={result.evidence_slot_package}
            onSelectEvidenceMatch={onSelectMatch}
          />
        </div>
      )}
      {matches.length > 0 && (
        <div className="mt-2 max-h-56 space-y-1.5 overflow-y-auto">
          {matches.slice(0, 6).map((match, index) => (
            <button
              key={`${match.chunk_id || index}`}
              type="button"
              onClick={() => onSelectMatch(match)}
              className="w-full rounded border border-slate-100 bg-slate-50 px-2 py-1.5 text-left text-[11px] leading-4 text-slate-700 hover:border-blue-100 hover:bg-blue-50"
            >
              <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-slate-400">
                <span>{String(match.chunk_id || `chunk-${index + 1}`)}</span>
                <span>p.{match.page || '-'}{match.page_end && match.page_end !== match.page ? `-${match.page_end}` : ''}</span>
                <span>bbox {String(match.bbox_count ?? getRetrievalMatchAnchors(match).length)}</span>
                {getRetrievalContributionBadges(match, index).map((badge) => (
                  <span
                    key={badge.key}
                    className={`rounded px-1.5 py-0.5 text-[10px] font-medium ring-1 ${badge.className}`}
                  >
                    {badge.label}
                  </span>
                ))}
              </div>
              <p className="line-clamp-2 break-words">{String(match.text || '')}</p>
            </button>
          ))}
        </div>
      )}
    </section>
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

      <div className="space-y-1">
        <p className="text-xs text-gray-400">评审问题</p>
        <p className="text-sm text-gray-700 leading-relaxed">{getIssueDisplayTitle(item)}</p>
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
function RightPane({ item, conditionA, evidenceRef, sessionId, ruleTopics }: {
  item?: ReviewItem;
  conditionA: boolean;
  evidenceRef: React.RefObject<HTMLDivElement | null>;
  sessionId: string;
  ruleTopics: ReviewRuleTopic[];
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
  const parsedReasoning = parseReasoning(item.ai_reasoning);
  const reasoning = parsedReasoning
    ? {
        ...parsedReasoning,
        evidence_slot_package: item.evidence_slot_package ?? parsedReasoning.evidence_slot_package,
        formula_check_results: item.formula_check_results ?? parsedReasoning.formula_check_results,
        earthwork_audit_results: item.earthwork_audit_results ?? parsedReasoning.earthwork_audit_results,
        project_composition_consistency: item.project_composition_consistency ?? parsedReasoning.project_composition_consistency,
        review_status: item.review_status ?? parsedReasoning.review_status,
        conclusion_type: item.conclusion_type ?? parsedReasoning.conclusion_type,
      }
    : item.evidence_slot_package || item.formula_check_results || item.earthwork_audit_results
      ? {
          evidence_slot_package: item.evidence_slot_package,
          formula_check_results: item.formula_check_results,
          earthwork_audit_results: item.earthwork_audit_results,
          project_composition_consistency: item.project_composition_consistency,
          review_status: item.review_status,
          conclusion_type: item.conclusion_type,
        }
      : null;
  const ruleContext = findReviewRuleContext(ruleTopics, reasoning?.rule_id, item.id);
  const isRagIssue = item.source_type === 'hybrid';
  const structuredFacts = Array.isArray(reasoning?.structured_facts) ? reasoning.structured_facts : [];
  const crossFindings = Array.isArray(reasoning?.cross_chapter_findings) ? reasoning.cross_chapter_findings : [];
  const reviewTopic = reasoning?.review_topic || (ruleContext ? { name: ruleContext.topic.topic_name } : null);
  const reviewItem = reasoning?.review_item || (ruleContext ? { name: ruleContext.checkItem.review_sub_type } : null);
  const reviewLogic = Array.isArray(reasoning?.review_logic) && reasoning.review_logic.length > 0
    ? reasoning.review_logic
    : ruleContext?.checkItem.review_logic ?? [];
  const evidenceScope = reasoning?.evidence_scope || ruleContext?.checkItem.evidence_scope || {};
  const ruleExecution = reasoning?.rule_execution || (ruleContext?.checkItem.reasoning_process ? { plan: ruleContext.checkItem.reasoning_process } : null);
  const executionResult = ruleExecution?.result;
  const evidenceSlotPackage = reasoning?.evidence_slot_package as EvidenceSlotPackage | undefined;
  const formulaCheckResults = reasoning?.formula_check_results as FormulaCheckResults | undefined;
  const projectComposition = reasoning?.project_composition_consistency as ProjectCompositionConsistency | undefined;
  const earthworkAuditChecks = toRecordArray(reasoning?.earthwork_audit_results?.checks);
  const reviewResult = getIssueReviewResult(item);

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
              ? '当前结果由 MinerU 解析数据 + LangExtract 证据抽取 + Chroma/SiliconFlow RAG 召回 + 水保规则裁决生成，证据片段携带页码、chunk 锚点与 bbox 节点信息。'
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
            {(reviewTopic || reviewItem || reviewLogic.length > 0) && (
              <div className="rounded-lg border border-sky-100 bg-sky-50/70 px-3 py-2 text-xs space-y-1">
                <p className="text-sky-700" style={{ fontWeight: 600 }}>审查路径</p>
                <p>
                  {reviewTopic?.name || '未识别主题'} → {reviewItem?.name || '未识别审查项'} → {reasoning.rule_name}
                </p>
                <p className="text-gray-500">
                  逻辑：{reviewLogic.map((logic: any) => logic.label || logic.type).filter(Boolean).join('、') || '-'}
                </p>
                <p className="text-gray-500">
                  证据范围：
                  章节 {(evidenceScope.chapters || []).join('、') || '-'} ·
                  表格 {(evidenceScope.tables || []).join('、') || '-'} ·
                  附件 {(evidenceScope.attachments || []).join('、') || '-'}
                </p>
              </div>
            )}
            {ruleExecution && (
              <div className="rounded-lg border border-violet-100 bg-violet-50/60 px-3 py-2 text-xs space-y-1">
                <p className="text-violet-700" style={{ fontWeight: 600 }}>规则预执行</p>
                <p>
                  状态：{executionResult?.execution_status || '待重新执行'} ·
                  需要 LLM 复核：{executionResult ? (executionResult.llm_required ? '是' : '否') : '-'}
                </p>
                <p className="text-gray-500">
                  命中字段：{(executionResult?.matched_target_fields || []).join('、') || '-'}
                </p>
                <p className="text-gray-500">
                  待核字段：{(executionResult?.missing_target_fields || ruleContext?.checkItem.target_fields || []).slice(0, 8).join('、') || '-'}
                </p>
              </div>
            )}
            <p>实际情况：{reasoning.actual_value}</p>
            <p>期望要求：{reasoning.expected_value}</p>
            <p className="text-xs text-gray-400">
              证据节点 {reasoning.evidence_nodes?.filter(Boolean).length ?? 0} 个 ·
              bbox {reasoning.source_bbox_list?.length ?? 0} 个 · 状态 {reasoning.review_status}
            </p>
            <p className="text-xs text-gray-400">
              结构化事实 {structuredFacts.length} 个 · 跨章节核验 {crossFindings.length} 条
            </p>
            {reviewResult && (
              <ReviewResultDetailPanel result={reviewResult} />
            )}
            {structuredFacts.length > 0 && (
              <div className="rounded-lg border border-emerald-100 bg-emerald-50/60 px-3 py-2 text-xs space-y-1">
                <p className="text-emerald-700" style={{ fontWeight: 600 }}>LangExtract 结构化事实</p>
                {structuredFacts.slice(0, 4).map((fact: any, index: number) => (
                  <p key={fact.fact_id || index} className="text-gray-700">
                    {fact.field_label || fact.field_name}：{fact.value || '未见明确值'}
                    <span className="text-gray-400">
                      {' '}· 第 {(fact.page_range || []).join('-') || '-'} 页 · {fact.chunk_id || '-'} · bbox {fact.bbox_count ?? fact.bbox_list?.length ?? 0}
                    </span>
                  </p>
                ))}
              </div>
            )}
            {crossFindings.length > 0 && (
              <div className="rounded-lg border border-amber-100 bg-amber-50/70 px-3 py-2 text-xs space-y-1">
                <p className="text-amber-700" style={{ fontWeight: 600 }}>跨章节核验线索</p>
                {crossFindings.slice(0, 3).map((finding: any, index: number) => (
                  <div key={finding.finding_id || index} className="text-gray-700">
                    <p>{finding.description}</p>
                    <p className="text-gray-400">
                      实际：{truncateText(finding.actual_value, 90)} · 页码：{(finding.source_pages || []).join('、') || '-'} · bbox {finding.bbox_count ?? finding.bbox_list?.length ?? 0}
                    </p>
                  </div>
                ))}
              </div>
            )}
            {projectComposition && (
              <ProjectCompositionComparisonPanel
                comparison={projectComposition}
                onSelectEvidenceMatch={() => undefined}
              />
            )}
            {evidenceSlotPackage && (
              <EvidenceSlotPackagePanel
                packageData={evidenceSlotPackage}
                onSelectEvidenceMatch={() => undefined}
              />
            )}
            {formulaCheckResults && (
              <FormulaCheckResultsPanel results={formulaCheckResults} />
            )}
            {earthworkAuditChecks.length > 0 && (
              <PreviewSection title={`土石方结构化审计 (${earthworkAuditChecks.length})`}>
                {earthworkAuditChecks.map((check, index) => (
                  <div key={String(check.audit_check_id || index)} className="rounded bg-slate-50 px-2 py-1.5 text-[11px] leading-4 text-slate-600">
                    <span className="font-medium text-slate-700">{String(check.label || check.audit_check_id || '-')}</span>
                    <span className={`ml-1 rounded px-1.5 py-0.5 text-[10px] ${statusClassName(String(check.status || ''))}`}>
                      {String(check.status || '-')}
                    </span>
                    <KeyValue label="缺字段" value={toStringArray(check.missing_fields).join('、') || '-'} />
                    <KeyValue label="来源事实" value={toStringArray(check.source_fact_ids).join('、') || '-'} />
                  </div>
                ))}
              </PreviewSection>
            )}
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

function ListDraftField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="block min-w-0 text-[11px] text-slate-500">
      {label}
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 h-12 w-full resize-none rounded border border-blue-100 bg-white px-2 py-1 text-xs text-slate-700"
        placeholder="逗号或换行分隔"
      />
    </label>
  );
}

function ExpertBriefField({
  label,
  value,
  onChange,
  placeholder,
  rows = 3,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  rows?: number;
}) {
  return (
    <label className="block min-w-0 text-[11px] text-slate-500">
      {label}
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        rows={rows}
        className="mt-1 w-full resize-none rounded border border-blue-100 bg-white px-2 py-1.5 text-xs leading-5 text-slate-700"
        placeholder={placeholder}
      />
    </label>
  );
}

function CheckItemDraftModal({
  draft,
  topic,
  executorOptions,
  ruleOptions,
  executorBindingBlocked,
  isSaving,
  isPreviewing,
  previewResult,
  onChange,
  onCancel,
  onPreview,
  onSave,
}: {
  draft: ConfigDraft;
  topic?: ReviewRuleTopic;
  executorOptions: ExecutorType[];
  ruleOptions: TopicRuleOption[];
  executorBindingBlocked: boolean;
  isSaving: boolean;
  isPreviewing: boolean;
  previewResult: PreviewCheckItemResponse | null;
  onChange: (draft: ConfigDraft) => void;
  onCancel: () => void;
  onPreview: () => void | Promise<void>;
  onSave: () => void | Promise<void>;
}) {
  const patchDraft = (patch: Partial<ConfigDraft>) => onChange({ ...draft, ...patch });
  const patchAdvancedDraft = (patch: Partial<ConfigDraft>) => onChange({ ...draft, ...patch, advancedDirty: true });
  const patchExpertBrief = (patch: Partial<ExpertReviewBrief>) => {
    const nextBrief = { ...draft.expertBrief, ...patch };
    const nextDraft: ConfigDraft = { ...draft, expertBrief: nextBrief };
    if (patch.item_name !== undefined) nextDraft.review_sub_type = patch.item_name;
    onChange(nextDraft);
  };
  const canSave = draft.review_sub_type.trim().length > 0 && !executorBindingBlocked;

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-slate-900/40 px-4">
      <div className="flex max-h-[88vh] w-full max-w-6xl flex-col overflow-hidden rounded-md bg-white shadow-2xl">
        <div className="flex shrink-0 items-start justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <div className="min-w-0">
            <h3 className="text-sm text-slate-800" style={{ fontWeight: 700 }}>
              {draft.id ? '编辑审查项' : '新增审查项'}
            </h3>
            <p className="mt-0.5 truncate text-[11px] text-slate-500">
              当前审查主题：{topic?.topic_name ?? '未选择主题'}
            </p>
          </div>
          <button
            type="button"
            onClick={onCancel}
            aria-label="关闭审查项编辑弹层"
            className="shrink-0 rounded p-1 text-slate-400 hover:bg-slate-50 hover:text-slate-600"
          >
            <XCircle className="h-4 w-4" />
          </button>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-1 overflow-hidden md:grid-cols-[minmax(0,1fr)_minmax(320px,0.9fr)]">
          <div className="min-h-0 space-y-3 overflow-y-auto px-4 py-3">
            <label className="block text-[11px] text-slate-500">
              审查项名称
              <input
                value={draft.expertBrief.item_name}
                onChange={(event) => patchExpertBrief({ item_name: event.target.value })}
                className="mt-1 w-full rounded border border-blue-100 bg-white px-2 py-1 text-xs text-slate-700"
                placeholder="审查项名称"
              />
            </label>

            <ExpertBriefField
              label="审查什么"
              value={draft.expertBrief.review_objective}
              onChange={(value) => patchExpertBrief({ review_objective: value })}
              placeholder="用自然语言写清楚本项要审查的对象、范围和目标"
            />
            <ExpertBriefField
              label="去哪里找证据"
              value={draft.expertBrief.evidence_instruction}
              onChange={(value) => patchExpertBrief({ evidence_instruction: value })}
              placeholder="说明应查看哪些章节、表格、附件、图纸、法规上下文或原文线索"
            />
            <ExpertBriefField
              label="判断依据/经验/法规口径"
              value={draft.expertBrief.judgement_basis}
              onChange={(value) => patchExpertBrief({ judgement_basis: value })}
              placeholder="说明按什么法规、行业经验、项目口径或审查经验判断"
              rows={4}
            />
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              <ExpertBriefField
                label="通过条件"
                value={draft.expertBrief.pass_condition}
                onChange={(value) => patchExpertBrief({ pass_condition: value })}
                placeholder="什么情况可以判定通过"
                rows={3}
              />
              <ExpertBriefField
                label="问题条件"
                value={draft.expertBrief.issue_condition}
                onChange={(value) => patchExpertBrief({ issue_condition: value })}
                placeholder="什么情况应判定为问题"
                rows={3}
              />
            </div>
            <ExpertBriefField
              label="法规/口径补充"
              value={draft.expertBrief.regulation_text ?? ''}
              onChange={(value) => patchExpertBrief({ regulation_text: value })}
              placeholder="可选：粘贴具体法规原文、地方口径或补充说明"
            />

            <details className="border-t border-slate-100 pt-3">
              <summary className="cursor-pointer select-none text-xs text-slate-600">
                高级结构化参数
              </summary>
              <div className="mt-3 space-y-3">
                <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                  <label className="min-w-0 text-[11px] text-slate-500">
                    执行类型
                    <select
                      value={draft.executor_type_id}
                      onChange={(event) => {
                        const executor = executorOptions.find((item) => item.id === event.target.value);
                        patchAdvancedDraft({
                          executor_type_id: event.target.value,
                          review_type: executor?.label ?? draft.review_type,
                        });
                      }}
                      className="mt-1 w-full rounded border border-blue-100 bg-white px-2 py-1 text-xs text-slate-700"
                    >
                      {executorOptions.map((executor) => (
                        <option key={executor.id} value={executor.id} disabled={!executor.enabled}>
                          {executor.label}{executor.enabled ? '' : '（停用）'}
                        </option>
                      ))}
                    </select>
                    {executorBindingBlocked && (
                      <span className="mt-1 block text-[10px] text-rose-600">
                        停用执行类型不能绑定到启用审查项
                      </span>
                    )}
                  </label>

                  <label className="min-w-0 text-[11px] text-slate-500">
                    规则模板
                    <select
                      value={draft.rule_id}
                      onChange={(event) => {
                        const ruleId = event.target.value;
                        const template = findTopicRuleTemplate(topic, ruleId);
                        if (!template) {
                          patchAdvancedDraft({ rule_id: ruleId });
                          return;
                        }
                        patchAdvancedDraft(applyRuleTemplateToDraft(draft, template));
                      }}
                      className="mt-1 w-full rounded border border-blue-100 bg-white px-2 py-1 text-xs text-slate-700"
                    >
                      <option value="">不引用模板</option>
                      {ruleOptions.map((rule) => (
                        <option key={rule.rule_id} value={rule.rule_id}>{rule.label}</option>
                      ))}
                    </select>
                  </label>
                </div>

                <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                  <ListDraftField label="章节范围" value={draft.evidenceChaptersInput} onChange={(value) => patchAdvancedDraft({ evidenceChaptersInput: value })} />
                  <ListDraftField label="表格范围" value={draft.evidenceTablesInput} onChange={(value) => patchAdvancedDraft({ evidenceTablesInput: value })} />
                  <ListDraftField label="附件范围" value={draft.evidenceAttachmentsInput} onChange={(value) => patchAdvancedDraft({ evidenceAttachmentsInput: value })} />
                  <ListDraftField label="法规范围" value={draft.evidenceRegulationsInput} onChange={(value) => patchAdvancedDraft({ evidenceRegulationsInput: value })} />
                </div>

                <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                  <ListDraftField label="目标字段" value={draft.targetFieldsInput} onChange={(value) => patchAdvancedDraft({ targetFieldsInput: value })} />
                  <ListDraftField label="法规条款" value={draft.regulationClausesInput} onChange={(value) => patchAdvancedDraft({ regulationClausesInput: value })} />
                </div>

                <label className="block text-[11px] text-slate-500">
                  默认说明/结论
                  <textarea
                    value={draft.conclusion}
                    onChange={(event) => patchAdvancedDraft({ conclusion: event.target.value })}
                    className="mt-1 h-16 w-full resize-none rounded border border-blue-100 bg-white px-2 py-1 text-xs text-slate-700"
                    placeholder="默认审查结论/执行说明"
                  />
                </label>

                <label className="block text-[11px] text-slate-500">
                  审查规则/判断标准
                  <textarea
                    value={draft.reviewCriteria}
                    onChange={(event) => patchAdvancedDraft({ reviewCriteria: event.target.value })}
                    className="mt-1 h-20 w-full resize-none rounded border border-blue-100 bg-white px-2 py-1 text-xs text-slate-700"
                    placeholder="说明基于什么规则进行审查"
                  />
                </label>

                <label className="block text-[11px] text-slate-500">
                  预期结果/通过条件
                  <textarea
                    value={draft.expectedResult}
                    onChange={(event) => patchAdvancedDraft({ expectedResult: event.target.value })}
                    className="mt-1 h-16 w-full resize-none rounded border border-blue-100 bg-white px-2 py-1 text-xs text-slate-700"
                    placeholder="说明审查通过时应看到的结果"
                  />
                </label>

                <ListDraftField label="错误条件" value={draft.failureConditionsInput} onChange={(value) => patchAdvancedDraft({ failureConditionsInput: value })} />

                <label className="block text-[11px] text-slate-500">
                  Evidence Slots JSON
                  <textarea
                    value={draft.evidenceSlotsJson}
                    onChange={(event) => patchAdvancedDraft({ evidenceSlotsJson: event.target.value })}
                    className="mt-1 h-28 w-full resize-none rounded border border-blue-100 bg-white px-2 py-1 font-mono text-[11px] leading-4 text-slate-700"
                    placeholder='[{"id":"project_overview","label":"项目概要建设内容","required":true}]'
                  />
                </label>

                <label className="block text-[11px] text-slate-500">
                  Formula Checks JSON
                  <textarea
                    value={draft.formulaChecksJson}
                    onChange={(event) => patchAdvancedDraft({ formulaChecksJson: event.target.value })}
                    className="mt-1 h-28 w-full resize-none rounded border border-blue-100 bg-white px-2 py-1 font-mono text-[11px] leading-4 text-slate-700"
                    placeholder='[{"id":"earthwork_total_balance","left_fields":["excavation_volume"],"right_fields":["fill_volume"]}]'
                  />
                </label>
              </div>
            </details>
          </div>

          <PreviewResultPanel result={previewResult} isLoading={isPreviewing} onSelectEvidenceMatch={handleSelectPreviewMatch} />
        </div>

        <div className="flex shrink-0 items-center justify-between gap-2 border-t border-slate-100 px-4 py-3">
          <label className="flex items-center gap-1.5 text-xs text-slate-600">
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(event) => patchDraft({ enabled: event.target.checked })}
              className="h-3.5 w-3.5 rounded border-blue-100"
            />
            启用
          </label>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onCancel} className="rounded px-3 py-1.5 text-xs text-slate-500 hover:bg-slate-50">
              取消
            </button>
            <button
              type="button"
              onClick={onPreview}
              disabled={isPreviewing || !canSave}
              className="inline-flex items-center gap-1.5 rounded border border-blue-200 px-3 py-1.5 text-xs text-blue-600 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isPreviewing && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {isPreviewing ? '试审中' : '用当前简报试审'}
            </button>
            <button
              type="button"
              onClick={onSave}
              disabled={isSaving || !canSave}
              className="rounded bg-blue-600 px-3 py-1.5 text-xs text-white disabled:opacity-50"
            >
              {isSaving ? '保存中' : '保存规则'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function PreviewResultPanel({
  result,
  isLoading,
  onSelectEvidenceMatch,
}: {
  result: PreviewCheckItemResponse | null;
  isLoading: boolean;
  onSelectEvidenceMatch: (match: RetrievalMatch) => void;
}) {
  if (isLoading) {
    return (
      <div className="min-h-0 overflow-y-auto border-t border-slate-100 bg-slate-50 px-4 py-3 md:border-l md:border-t-0">
        <div className="flex h-full min-h-64 items-center justify-center gap-2 text-xs text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
          正在执行 RAG Agent 召回并调用 LLM 试审…
        </div>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="min-h-0 overflow-y-auto border-t border-slate-100 bg-slate-50 px-4 py-3 md:border-l md:border-t-0">
        <div className="flex h-full min-h-64 items-center justify-center rounded border border-dashed border-slate-200 bg-white px-4 text-center text-xs leading-5 text-slate-400">
          填写左侧专家简报后点击“用当前简报试审”，这里会展示 RAG chunk 召回、LLM 审查结论、法规上下文和 agent trace。
        </div>
      </div>
    );
  }

  const evidence = result.evidence_bundle ?? {};
  const precheck = result.precheck_result ?? {};
  const conclusion = result.review_conclusion ?? {};
  const retrievalMatches = toRecordArray(evidence.retrieval_matches) as RetrievalMatch[];
  const structuredFacts = toUnknownArray(evidence.structured_facts);
  const crossReferenceFindings = toUnknownArray(evidence.cross_reference_findings);
  const projectComposition = evidence.project_composition_consistency;
  const evidenceSlotPackage = evidence.evidence_slot_package;
  const formulaCheckResults = evidence.formula_check_results;
  const langextractGrounding = toUnknownArray(evidence.langextract_grounding);
  const regulationContext = toRecordArray(evidence.regulation_context);
  const checks = toRecordArray(precheck.checks);
  const agentTrace: PreviewAgentTrace = result.agent_trace ?? {};
  const sourceLabel = evidence.source === 'rag_agent' ? 'RAG Agent' : String(evidence.source ?? '-');

  return (
    <div className="min-h-0 space-y-3 overflow-y-auto border-t border-slate-100 bg-slate-50 px-4 py-3 md:border-l md:border-t-0">
      <div className="rounded border border-slate-200 bg-white px-3 py-2">
        <div className="mb-2 flex items-center justify-between gap-2">
          <div className="min-w-0">
            <span className="text-xs text-slate-700" style={{ fontWeight: 700 }}>真实召回试审</span>
            <p className="mt-0.5 text-[10px] text-slate-400">
              来源：{sourceLabel} · 持久化：{agentTrace.persisted ? '是' : '否'}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <span className="rounded bg-blue-50 px-1.5 py-0.5 text-[10px] text-blue-700">{sourceLabel}</span>
            <span className={`rounded px-1.5 py-0.5 text-[10px] ${statusClassName(conclusion.status)}`}>
              {conclusion.status || 'pending'}
            </span>
          </div>
        </div>
        <p className="text-xs leading-5 text-slate-700">{conclusion.summary || '暂无摘要'}</p>
        <div className="mt-2 space-y-1">
          <KeyValue label="实际情况" value={conclusion.actual_value || '-'} />
          <KeyValue label="预期要求" value={conclusion.expected_value || '-'} />
          <KeyValue label="修改建议" value={conclusion.fix_suggestion || '-'} />
          <KeyValue label="置信度" value={conclusion.confidence === undefined ? '-' : String(conclusion.confidence)} />
          <KeyValue label="下一步" value={conclusion.next_action || '-'} />
        </div>
      </div>

      <PreviewSection title="字段命中">
        <KeyValue label="已命中" value={toStringArray(evidence.matched_target_fields).join('、') || '-'} />
        <KeyValue label="缺失字段" value={toStringArray(evidence.missing_target_fields).join('、') || '-'} />
      </PreviewSection>

      {projectComposition && (
        <ProjectCompositionComparisonPanel
          comparison={projectComposition}
          onSelectEvidenceMatch={onSelectEvidenceMatch}
        />
      )}

      {evidenceSlotPackage && (
        <EvidenceSlotPackagePanel
          packageData={evidenceSlotPackage}
          onSelectEvidenceMatch={onSelectEvidenceMatch}
        />
      )}

      {formulaCheckResults && (
        <FormulaCheckResultsPanel results={formulaCheckResults} />
      )}

      <PreviewSection title={`RAG 证据 chunk (${retrievalMatches.length})`}>
        {retrievalMatches.length === 0 ? (
          <EmptyPreviewLine text="未召回 RAG chunk" />
        ) : retrievalMatches.map((match, index) => (
          <button
            key={`${match.chunk_id || index}`}
            type="button"
            onClick={() => onSelectEvidenceMatch(match)}
            className="w-full rounded bg-slate-50 px-2 py-1.5 text-left text-[11px] leading-4 text-slate-700 ring-1 ring-transparent hover:bg-blue-50 hover:ring-blue-100"
          >
            <div className="mb-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[10px] text-slate-400">
              <span>{String(match.chunk_id || `chunk-${index + 1}`)}</span>
              <span>页码 {match.page || '-'}{match.page_end && match.page_end !== match.page ? `-${match.page_end}` : ''}</span>
              <span>{String(match.section || '-')}</span>
              <span>bbox {String(match.bbox_count ?? getRetrievalMatchAnchors(match).length)}</span>
              <span>score {formatScore(match.score)}</span>
              <span>rerank {formatScore(match.rerank_score)}</span>
            </div>
            <p className="whitespace-pre-wrap break-words">{String(match.text || '')}</p>
          </button>
        ))}
      </PreviewSection>

      <PreviewJsonList title={`结构化事实 (${structuredFacts.length})`} items={structuredFacts} emptyText="暂无 structured_facts" />
      <PreviewJsonList title={`跨章节/引用线索 (${crossReferenceFindings.length})`} items={crossReferenceFindings} emptyText="暂无 cross_reference_findings" />
      <PreviewJsonList title={`LangExtract Grounding (${langextractGrounding.length})`} items={langextractGrounding} emptyText="暂无 langextract_grounding" />
      <PreviewJsonList title={`法规条款上下文 (${regulationContext.length})`} items={regulationContext} emptyText="暂无 regulation_context" />

      <PreviewSection title={`预检查 (${checks.length})`}>
        <KeyValue label="执行器" value={`${precheck.executor_type_id || '-'} / ${precheck.handler_id || '-'}`} />
        <KeyValue label="状态" value={precheck.execution_status || '-'} />
        <KeyValue label="摘要" value={precheck.summary || '-'} />
        <KeyValue label="下一步" value={precheck.next_action || '-'} />
        {checks.length === 0 ? (
          <EmptyPreviewLine text="暂无 checks" />
        ) : checks.map((check, index) => (
          <div key={index} className="rounded bg-slate-50 px-2 py-1.5 text-[11px] leading-4 text-slate-600">
            {formatCompactJson(check)}
          </div>
        ))}
      </PreviewSection>

      <PreviewSection title="Agent Trace">
        <KeyValue label="模式" value={agentTrace.retrieval_mode || '-'} />
        <KeyValue label="模型" value={agentTrace.llm_model || '-'} />
        <KeyValue label="chunks" value={agentTrace.chunk_count === undefined ? '-' : String(agentTrace.chunk_count)} />
        <KeyValue label="facts" value={agentTrace.facts_available ? '可用' : '不可用'} />
        <KeyValue label="query" value={agentTrace.query || '-'} />
      </PreviewSection>

      <PreviewSection title="规则改进建议">
        {result.suggested_rule_improvements.length === 0 ? (
          <EmptyPreviewLine text="暂无建议" />
        ) : result.suggested_rule_improvements.map((item, index) => (
          <p key={index} className="rounded bg-blue-50 px-2 py-1.5 text-[11px] leading-4 text-blue-700">
            {item}
          </p>
        ))}
      </PreviewSection>
    </div>
  );
}

function ProjectCompositionComparisonPanel({
  comparison,
  onSelectEvidenceMatch,
}: {
  comparison: ProjectCompositionConsistency;
  onSelectEvidenceMatch: (match: RetrievalMatch) => void;
}) {
  const fields = Array.isArray(comparison.field_comparisons) ? comparison.field_comparisons : [];
  const keyFindings = toStringArray(comparison.key_findings);
  const bodyQuote = typeof comparison.evidence_quotes?.body === 'string' ? comparison.evidence_quotes.body : '';
  const referenceQuote = typeof comparison.evidence_quotes?.reference === 'string' ? comparison.evidence_quotes.reference : '';
  return (
    <PreviewSection title="项目组成一致性">
      <div className="flex flex-wrap items-center gap-2 text-[11px]">
        <span className={`rounded px-1.5 py-0.5 text-[10px] ${statusClassName(comparison.status)}`}>
          {comparison.status || 'needs_review'}
        </span>
        <span className="min-w-0 flex-1 text-slate-600">{comparison.reason || '待复核项目组成与建设内容。'}</span>
      </div>
      {comparison.judgement_basis && (
        <div className="rounded bg-blue-50 px-2 py-1.5 text-[11px] leading-4 text-blue-700">
          判断依据：{comparison.judgement_basis}
        </div>
      )}
      {keyFindings.length > 0 && (
        <div className="rounded bg-amber-50 px-2 py-1.5 text-[11px] leading-4 text-amber-800">
          {keyFindings.slice(0, 3).map((item) => (
            <p key={item}>判定过程：{item}</p>
          ))}
        </div>
      )}
      {(bodyQuote || referenceQuote) && (
        <div className="space-y-1 rounded bg-slate-50 px-2 py-1.5 text-[11px] leading-4 text-slate-600">
          {bodyQuote && <p>正文原话：{bodyQuote.replace(/^正文原话：/, '')}</p>}
          {referenceQuote && <p>附件/设计原话：{referenceQuote.replace(/^附件\/设计原话：/, '')}</p>}
        </div>
      )}
      <div className="grid gap-2 sm:grid-cols-2">
        <ProjectCompositionSourceButton
          label="正文项目概况"
          source={comparison.body_source}
          onSelectEvidenceMatch={onSelectEvidenceMatch}
        />
        <ProjectCompositionSourceButton
          label="附件/设计文件"
          source={comparison.reference_source}
          onSelectEvidenceMatch={onSelectEvidenceMatch}
        />
      </div>
      {fields.length === 0 ? (
        <EmptyPreviewLine text="暂无字段级比较" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[420px] border-collapse text-[11px]">
            <thead>
              <tr className="border-b border-slate-100 text-left text-slate-400">
                <th className="py-1 pr-2 font-medium">字段</th>
                <th className="py-1 pr-2 font-medium">正文</th>
                <th className="py-1 pr-2 font-medium">附件</th>
                <th className="py-1 pr-2 font-medium">差异</th>
                <th className="py-1 font-medium">状态</th>
              </tr>
            </thead>
            <tbody>
              {fields.map((field) => (
                <tr key={field.field || field.label} className="border-b border-slate-50 text-slate-600">
                  <td className="py-1 pr-2">{field.label || field.field || '-'}</td>
                  <td className="py-1 pr-2">{formatNullableNumber(field.body_value)}</td>
                  <td className="py-1 pr-2">{formatNullableNumber(field.reference_value)}</td>
                  <td className="py-1 pr-2">{formatNullableNumber(field.difference)}</td>
                  <td className="py-1">
                    <span className={`rounded px-1.5 py-0.5 text-[10px] ${statusClassName(field.status)}`}>
                      {field.status || '-'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PreviewSection>
  );
}

function ProjectCompositionSourceButton({
  label,
  source,
  onSelectEvidenceMatch,
}: {
  label: string;
  source?: ProjectCompositionSource | null;
  onSelectEvidenceMatch: (match: RetrievalMatch) => void;
}) {
  if (!source) {
    return <div className="rounded bg-slate-50 px-2 py-1.5 text-[11px] text-slate-400">{label}：未定位</div>;
  }
  const match = source as RetrievalMatch;
  return (
    <button
      type="button"
      onClick={() => onSelectEvidenceMatch(match)}
      className="rounded bg-slate-50 px-2 py-1.5 text-left text-[11px] leading-4 text-slate-600 ring-1 ring-transparent hover:bg-blue-50 hover:ring-blue-100"
    >
      <span className="block text-[10px] text-slate-400">{label} · {source.material_type || '-'}</span>
      <span className="block font-medium text-slate-700">{String(source.chunk_id || '-')} · p.{source.page || '-'}</span>
      <span className="line-clamp-2 break-words">{String(source.text || '')}</span>
    </button>
  );
}

function EvidenceSlotPackagePanel({
  packageData,
  onSelectEvidenceMatch,
}: {
  packageData: EvidenceSlotPackage;
  onSelectEvidenceMatch: (match: RetrievalMatch) => void;
}) {
  const slots = toRecordArray(packageData.slots);
  return (
    <PreviewSection title={`证据槽位 (${packageData.matched_required_slot_count ?? 0}/${packageData.required_slot_count ?? 0})`}>
      <KeyValue label="缺失必填" value={toStringArray(packageData.missing_required_slot_ids).join('、') || '-'} />
      <KeyValue label="截断" value={packageData.truncated ? `是，最多 ${packageData.slot_limit ?? '-'}` : '否'} />
      {slots.length === 0 ? (
        <EmptyPreviewLine text="暂无 evidence_slots" />
      ) : slots.map((slot, index) => (
        <EvidenceSlotCard
          key={String(slot.slot_id || index)}
          slot={slot}
          onSelectEvidenceMatch={onSelectEvidenceMatch}
        />
      ))}
    </PreviewSection>
  );
}

function EvidenceSlotCard({
  slot,
  onSelectEvidenceMatch,
}: {
  slot: Record<string, unknown>;
  onSelectEvidenceMatch: (match: RetrievalMatch) => void;
}) {
  const matches = toRecordArray(slot.matches) as RetrievalMatch[];
  const promptMatches = toRecordArray(slot.prompt_matches) as RetrievalMatch[];
  const traceMatches = toRecordArray(slot.trace_matches) as RetrievalMatch[];
  const queries = toRecordArray(slot.queries);
  const visiblePromptMatches = promptMatches.length > 0 ? promptMatches : matches.slice(0, 3);
  return (
    <div className="rounded bg-slate-50 px-2 py-1.5 text-[11px] leading-4 text-slate-600">
      <div className="mb-1 flex flex-wrap items-center gap-1.5">
        <span className="font-medium text-slate-700">{String(slot.label || slot.slot_id || '-')}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] ${statusClassName(String(slot.status || ''))}`}>
          {String(slot.status || '-')}
        </span>
        {slot.required === true && <span className="rounded bg-rose-50 px-1.5 py-0.5 text-[10px] text-rose-700">必填</span>}
        {slot.truncated_queries === true && <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] text-amber-700">query 已截断</span>}
      </div>
      <KeyValue label="命中词" value={toStringArray(slot.matched_expected_terms).join('、') || '-'} />
      <KeyValue label="缺失词" value={toStringArray(slot.missing_expected_terms).join('、') || '-'} />
      <KeyValue label="命中数" value={`${String(slot.match_count ?? matches.length)} / 最少 ${String(slot.min_matches ?? 1)}`} />
      <KeyValue label="prompt" value={`${visiblePromptMatches.length} 条；trace ${traceMatches.length} 条`} />
      <KeyValue label="query" value={queries.map((item) => String(item.query || '')).filter(Boolean).join('；') || '-'} />
      {visiblePromptMatches.length === 0 ? (
        <div className="mt-1 rounded bg-white px-2 py-1 ring-1 ring-slate-100">
          <EmptyPreviewLine text="暂无命中 chunk" />
        </div>
      ) : visiblePromptMatches.map((match, index) => (
        <button
          key={`${match.chunk_id || index}`}
          type="button"
          onClick={() => onSelectEvidenceMatch(match)}
          className="mt-1 w-full rounded bg-white px-2 py-1 text-left text-[10px] text-slate-500 ring-1 ring-slate-100 hover:bg-blue-50 hover:ring-blue-100"
        >
          prompt · {String(match.chunk_id || '-')} · p.{match.page || '-'} · {toStringArray(match.retrieval_sources).join('+') || '-'} · {String(match.text || '').slice(0, 90)}
        </button>
      ))}
      {traceMatches.slice(0, 2).map((match, index) => (
        <button
          key={`trace-${match.chunk_id || index}`}
          type="button"
          onClick={() => onSelectEvidenceMatch(match)}
          className="mt-1 w-full rounded bg-white/70 px-2 py-1 text-left text-[10px] text-slate-400 ring-1 ring-slate-100 hover:bg-blue-50 hover:text-slate-500 hover:ring-blue-100"
        >
          trace · {String(match.chunk_id || '-')} · p.{match.page || '-'} · {toStringArray(match.retrieval_sources).join('+') || '-'} · {String(match.text || '').slice(0, 90)}
        </button>
      ))}
    </div>
  );
}

function FormulaCheckResultsPanel({ results }: { results: FormulaCheckResults }) {
  const checks = toRecordArray(results.checks);
  return (
    <PreviewSection title={`公式校验 (${results.pass_count ?? 0} pass / ${results.fail_count ?? 0} fail / ${results.missing_count ?? 0} missing / ${results.unsupported_count ?? 0} unsupported)`}>
      {checks.length === 0 ? (
        <EmptyPreviewLine text="暂无 formula_checks" />
      ) : checks.map((check, index) => (
        <FormulaCheckCard key={String(check.formula_check_id || index)} check={check} />
      ))}
    </PreviewSection>
  );
}

function FormulaCheckCard({ check }: { check: Record<string, unknown> }) {
  const fieldValues = check.field_values && typeof check.field_values === 'object' && !Array.isArray(check.field_values)
    ? check.field_values as Record<string, unknown>
    : {};
  return (
    <div className="rounded bg-slate-50 px-2 py-1.5 text-[11px] leading-4 text-slate-600">
      <div className="mb-1 flex flex-wrap items-center gap-1.5">
        <span className="font-medium text-slate-700">{String(check.label || check.formula_check_id || '-')}</span>
        <span className={`rounded px-1.5 py-0.5 text-[10px] ${statusClassName(String(check.status || ''))}`}>
          {String(check.status || '-')}
        </span>
      </div>
      <KeyValue label="表达式" value={String(check.expression || '-')} />
      <KeyValue label="失败原因" value={String(check.failure_reason || '-')} />
      <KeyValue label="左值" value={`${formatNullableNumber(check.left_value)} ${String(check.unit || '')}`} />
      <KeyValue label="右值" value={`${formatNullableNumber(check.right_value)} ${String(check.unit || '')}`} />
      <KeyValue label="差值" value={formatNullableNumber(check.difference)} />
      <KeyValue label="缺字段" value={toStringArray(check.missing_fields).join('、') || '-'} />
      <KeyValue label="不支持单位字段" value={toStringArray(check.unsupported_fields).join('、') || '-'} />
      <KeyValue label="配置错误" value={toStringArray(check.config_errors).join('、') || '-'} />
      <div className="mt-1 space-y-1">
        {Object.keys(fieldValues).length === 0 ? (
          <div className="rounded bg-white px-2 py-1 ring-1 ring-slate-100">
            <EmptyPreviewLine text="暂无 field_values" />
          </div>
        ) : Object.entries(fieldValues).map(([field, value]) => (
          <div key={field} className="rounded bg-white px-2 py-1 text-[10px] text-slate-500 ring-1 ring-slate-100">
            {field}: {formatCompactJson(value)}
          </div>
        ))}
      </div>
    </div>
  );
}

function PreviewSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-2 rounded border border-slate-200 bg-white px-3 py-2">
      <p className="text-xs text-slate-700" style={{ fontWeight: 700 }}>{title}</p>
      {children}
    </div>
  );
}

function PreviewJsonList({ title, items, emptyText }: { title: string; items: unknown[]; emptyText: string }) {
  return (
    <PreviewSection title={title}>
      {items.length === 0 ? (
        <EmptyPreviewLine text={emptyText} />
      ) : items.slice(0, 8).map((item, index) => (
        <div key={index} className="rounded bg-slate-50 px-2 py-1.5 text-[11px] leading-4 text-slate-600">
          {formatCompactJson(item)}
        </div>
      ))}
      {items.length > 8 && <p className="text-[10px] text-slate-400">另有 {items.length - 8} 条未展开</p>}
    </PreviewSection>
  );
}

function KeyValue({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <p className="grid grid-cols-[64px_minmax(0,1fr)] gap-2 text-[11px] leading-4">
      <span className="text-slate-400">{label}</span>
      <span className="min-w-0 break-words text-slate-600 [overflow-wrap:anywhere]">{value}</span>
    </p>
  );
}

function EmptyPreviewLine({ text }: { text: string }) {
  return <p className="text-[11px] text-slate-400">{text}</p>;
}

function buildCheckItemPayload(configDraft: ConfigDraft): CheckItemPayload {
  const expertBrief = normalizeExpertBrief(configDraft.expertBrief);
  const payload: CheckItemPayload = {
    topic_id: configDraft.topic_id,
    rule_id: configDraft.rule_id.trim(),
    executor_type_id: configDraft.executor_type_id,
    review_type: configDraft.review_type,
    review_sub_type: expertBrief.item_name || configDraft.review_sub_type,
    expert_brief: expertBrief,
    source_rule_snapshot: buildPayloadSourceRuleSnapshot(configDraft.sourceRuleSnapshot, expertBrief),
    enabled: configDraft.enabled,
  };

  if (configDraft.advancedDirty) {
    const conclusion = configDraft.conclusion.trim();
    if (conclusion) payload.conclusion = conclusion;

    const evidenceScope = buildEvidenceScope(configDraft);
    if (evidenceScope) payload.evidence_scope = evidenceScope;

    const targetFields = parseListInput(configDraft.targetFieldsInput);
    if (targetFields.length > 0) payload.target_fields = targetFields;

    const regulationClauses = parseListInput(configDraft.regulationClausesInput);
    if (regulationClauses.length > 0) payload.regulation_clauses = regulationClauses;

    const reviewCriteria = configDraft.reviewCriteria.trim();
    if (reviewCriteria) payload.review_criteria = reviewCriteria;

    const expectedResult = configDraft.expectedResult.trim();
    if (expectedResult) payload.expected_result = expectedResult;

    const failureConditions = parseListInput(configDraft.failureConditionsInput);
    if (failureConditions.length > 0) payload.failure_conditions = failureConditions;

    const evidenceSlots = parseJsonRecordList(configDraft.evidenceSlotsJson, 'Evidence Slots JSON');
    payload.evidence_slots = evidenceSlots;

    const formulaChecks = parseJsonRecordList(configDraft.formulaChecksJson, 'Formula Checks JSON');
    payload.formula_checks = formulaChecks;
  }

  return payload;
}

function buildPayloadSourceRuleSnapshot(
  sourceRuleSnapshot: Record<string, unknown>,
  expertBrief: ExpertReviewBrief,
): Record<string, unknown> {
  const snapshot: Record<string, unknown> = {
    expert_brief: expertBrief,
  };
  const source = sourceRuleSnapshot.ai_or_human_source;
  if (typeof source === 'string' && source.trim()) snapshot.ai_or_human_source = source;
  return snapshot;
}

function buildEvidenceScope(configDraft: ConfigDraft): Record<string, unknown> | undefined {
  const evidenceScope: Record<string, unknown> = {};
  const structuredEvidenceKeys = new Set(['chapters', 'tables', 'attachments', 'regulations']);

  Object.entries(configDraft.baseEvidenceScope).forEach(([key, value]) => {
    if (structuredEvidenceKeys.has(key)) return;
    if (isMeaningfulEvidenceValue(value)) evidenceScope[key] = value;
  });

  const chapters = parseListInput(configDraft.evidenceChaptersInput);
  if (chapters.length > 0) evidenceScope.chapters = chapters;

  const tables = parseListInput(configDraft.evidenceTablesInput);
  if (tables.length > 0) evidenceScope.tables = tables;

  const attachments = parseListInput(configDraft.evidenceAttachmentsInput);
  if (attachments.length > 0) evidenceScope.attachments = attachments;

  const regulations = parseListInput(configDraft.evidenceRegulationsInput);
  if (regulations.length > 0) evidenceScope.regulations = regulations;

  return Object.keys(evidenceScope).length > 0 ? evidenceScope : undefined;
}

function isMeaningfulEvidenceValue(value: unknown): boolean {
  if (Array.isArray(value)) return value.some((item) => isMeaningfulEvidenceValue(item));
  if (typeof value === 'boolean') return false;
  if (typeof value === 'string') return value.trim().length > 0;
  if (value && typeof value === 'object') return Object.values(value).some((item) => isMeaningfulEvidenceValue(item));
  return value !== null && value !== undefined;
}

function parseJsonRecordList(value: string, fieldLabel: string): Array<Record<string, unknown>> {
  const text = value.trim();
  if (!text) {
    throw new Error(`${fieldLabel} 必须是 JSON 数组；如需清空请填写 []`);
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error(`${fieldLabel} 不是合法 JSON 数组；如需清空请填写 []`);
  }
  if (!Array.isArray(parsed)) {
    throw new Error(`${fieldLabel} 必须是 JSON 数组`);
  }
  const invalidIndex = parsed.findIndex((item) => !item || typeof item !== 'object' || Array.isArray(item));
  if (invalidIndex >= 0) {
    throw new Error(`${fieldLabel} 第 ${invalidIndex + 1} 项必须是 JSON 对象`);
  }
  return parsed as Array<Record<string, unknown>>;
}

function parseListInput(value: string): string[] {
  return value
    .split(/[\n,，]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function joinListInput(values?: string[]): string {
  return (values ?? []).join('\n');
}

function formatJsonRecordList(value: unknown): string {
  return JSON.stringify(Array.isArray(value) ? value : [], null, 2);
}

function createEmptyExpertBrief(itemName = ''): ExpertReviewBrief {
  return {
    item_name: itemName,
    review_objective: '',
    evidence_instruction: '',
    judgement_basis: '',
    pass_condition: '',
    issue_condition: '',
    regulation_text: '',
  };
}

function normalizeExpertBrief(brief: ExpertReviewBrief): ExpertReviewBrief {
  return {
    item_name: brief.item_name.trim(),
    review_objective: brief.review_objective.trim(),
    evidence_instruction: brief.evidence_instruction.trim(),
    judgement_basis: brief.judgement_basis.trim(),
    pass_condition: brief.pass_condition.trim(),
    issue_condition: brief.issue_condition.trim(),
    regulation_text: brief.regulation_text?.trim() || undefined,
  };
}

function getExpertBriefFromSnapshot(snapshot: Record<string, unknown> | undefined): ExpertReviewBrief | null {
  const value = snapshot?.expert_brief;
  if (!value || typeof value !== 'object') return null;
  const record = value as Record<string, unknown>;
  return {
    item_name: typeof record.item_name === 'string' ? record.item_name : '',
    review_objective: typeof record.review_objective === 'string' ? record.review_objective : '',
    evidence_instruction: typeof record.evidence_instruction === 'string' ? record.evidence_instruction : '',
    judgement_basis: typeof record.judgement_basis === 'string' ? record.judgement_basis : '',
    pass_condition: typeof record.pass_condition === 'string' ? record.pass_condition : '',
    issue_condition: typeof record.issue_condition === 'string' ? record.issue_condition : '',
    regulation_text: typeof record.regulation_text === 'string' ? record.regulation_text : '',
  };
}

function buildEvidenceInstruction(item: ReviewCheckItem): string {
  const scopeParts = [
    formatScopedList('章节', item.evidence_scope?.chapters),
    formatScopedList('表格', item.evidence_scope?.tables),
    formatScopedList('附件', item.evidence_scope?.attachments),
    formatScopedList('法规', item.evidence_scope?.regulations),
    formatScopedList('目标字段', item.target_fields),
  ].filter(Boolean);
  return scopeParts.length > 0 ? scopeParts.join('；') : '';
}

function formatScopedList(label: string, values?: string[]): string {
  return values && values.length > 0 ? `${label}：${values.join('、')}` : '';
}

function buildExpertBriefFromStructured(item: ReviewCheckItem): ExpertReviewBrief {
  const criteria = item.review_criteria ?? getReasoningString(item.reasoning_process, 'criteria');
  const expectedResult = item.expected_result ?? getReasoningString(item.reasoning_process, 'expected_result');
  return {
    item_name: item.review_sub_type || item.rule_name || '',
    review_objective: item.conclusion || '',
    evidence_instruction: buildEvidenceInstruction(item),
    judgement_basis: criteria || '',
    pass_condition: expectedResult || '',
    issue_condition: joinListInput(item.failure_conditions),
    regulation_text: joinListInput(item.regulation_clauses),
  };
}

function getExpertBriefForItem(item: ReviewCheckItem): ExpertReviewBrief {
  return getExpertBriefFromSnapshot(item.source_rule_snapshot) ?? buildExpertBriefFromStructured(item);
}

function draftFromItem(item: ReviewCheckItem): ConfigDraft {
  const expertBrief = getExpertBriefForItem(item);
  return {
    id: item.id,
    topic_id: item.topic_id,
    rule_id: item.rule_id ?? '',
    executor_type_id: item.executor_type_id ?? item.review_logic_types?.[0] ?? 'manual_basic',
    review_type: item.review_type,
    review_sub_type: expertBrief.item_name || item.review_sub_type,
    conclusion: item.conclusion,
    baseEvidenceScope: item.evidence_scope ? { ...item.evidence_scope } : {},
    evidenceChaptersInput: joinListInput(item.evidence_scope?.chapters),
    evidenceTablesInput: joinListInput(item.evidence_scope?.tables),
    evidenceAttachmentsInput: joinListInput(item.evidence_scope?.attachments),
    evidenceRegulationsInput: joinListInput(item.evidence_scope?.regulations),
    targetFieldsInput: joinListInput(item.target_fields),
    regulationClausesInput: joinListInput(item.regulation_clauses),
    reviewCriteria: item.review_criteria ?? getReasoningString(item.reasoning_process, 'criteria'),
    expectedResult: item.expected_result ?? getReasoningString(item.reasoning_process, 'expected_result'),
    failureConditionsInput: joinListInput(item.failure_conditions),
    evidenceSlotsJson: formatJsonRecordList(item.evidence_slots),
    formulaChecksJson: formatJsonRecordList(item.formula_checks),
    expertBrief,
    sourceRuleSnapshot: item.source_rule_snapshot ?? {},
    advancedDirty: false,
    enabled: item.enabled ?? true,
  };
}

function draftFromRuleTemplate(topic: ReviewRuleTopic, item: ReviewCheckItem, executor?: ExecutorType): ConfigDraft {
  const sourceRuleSnapshot = buildSourceRuleSnapshot(item);
  const expertBrief = getExpertBriefFromSnapshot(sourceRuleSnapshot) ?? buildExpertBriefFromStructured(item);
  return {
    topic_id: topic.topic_id,
    rule_id: item.rule_id ?? '',
    executor_type_id: executor?.id ?? 'manual_basic',
    review_type: executor?.label ?? item.review_type ?? '人工基础核验',
    review_sub_type: expertBrief.item_name || item.review_sub_type || item.rule_name || `${topic.topic_name}审查项`,
    conclusion: item.conclusion || '待按配置执行审查。',
    baseEvidenceScope: item.evidence_scope ? { ...item.evidence_scope } : {},
    evidenceChaptersInput: joinListInput(item.evidence_scope?.chapters),
    evidenceTablesInput: joinListInput(item.evidence_scope?.tables),
    evidenceAttachmentsInput: joinListInput(item.evidence_scope?.attachments),
    evidenceRegulationsInput: joinListInput(item.evidence_scope?.regulations),
    targetFieldsInput: joinListInput(item.target_fields),
    regulationClausesInput: joinListInput(item.regulation_clauses),
    reviewCriteria: item.review_criteria || getReasoningString(item.reasoning_process, 'criteria') || item.conclusion || '',
    expectedResult: item.expected_result || getReasoningString(item.reasoning_process, 'expected_result') || item.conclusion || '',
    failureConditionsInput: joinListInput(item.failure_conditions),
    evidenceSlotsJson: formatJsonRecordList(item.evidence_slots),
    formulaChecksJson: formatJsonRecordList(item.formula_checks),
    expertBrief: expertBrief.item_name ? expertBrief : { ...expertBrief, item_name: `${topic.topic_name}审查项` },
    sourceRuleSnapshot,
    advancedDirty: true,
    enabled: true,
  };
}

function applyRuleTemplateToDraft(draft: ConfigDraft, item: ReviewCheckItem): ConfigDraft {
  const sourceRuleSnapshot = buildSourceRuleSnapshot(item);
  const expertBrief = getExpertBriefFromSnapshot(sourceRuleSnapshot) ?? buildExpertBriefFromStructured(item);
  return {
    ...draft,
    rule_id: item.rule_id ?? '',
    review_sub_type: expertBrief.item_name || item.review_sub_type || item.rule_name || draft.review_sub_type,
    conclusion: item.conclusion || draft.conclusion,
    baseEvidenceScope: item.evidence_scope ? { ...item.evidence_scope } : draft.baseEvidenceScope,
    evidenceChaptersInput: joinListInput(item.evidence_scope?.chapters),
    evidenceTablesInput: joinListInput(item.evidence_scope?.tables),
    evidenceAttachmentsInput: joinListInput(item.evidence_scope?.attachments),
    evidenceRegulationsInput: joinListInput(item.evidence_scope?.regulations),
    targetFieldsInput: joinListInput(item.target_fields),
    regulationClausesInput: joinListInput(item.regulation_clauses),
    reviewCriteria: item.review_criteria || getReasoningString(item.reasoning_process, 'criteria') || item.conclusion || draft.reviewCriteria,
    expectedResult: item.expected_result || getReasoningString(item.reasoning_process, 'expected_result') || item.conclusion || draft.expectedResult,
    failureConditionsInput: joinListInput(item.failure_conditions),
    evidenceSlotsJson: formatJsonRecordList(item.evidence_slots),
    formulaChecksJson: formatJsonRecordList(item.formula_checks),
    expertBrief,
    sourceRuleSnapshot,
    advancedDirty: true,
  };
}

function buildSourceRuleSnapshot(item: ReviewCheckItem): Record<string, unknown> {
  return {
    rule_id: item.rule_id ?? '',
    rule_name: item.rule_name ?? item.review_sub_type,
    review_type: item.review_type,
    review_sub_type: item.review_sub_type,
    conclusion: item.conclusion,
    evidence_scope: item.evidence_scope ?? {},
    target_fields: item.target_fields ?? [],
    regulation_clauses: item.regulation_clauses ?? [],
    review_criteria: item.review_criteria ?? '',
    expected_result: item.expected_result ?? '',
    failure_conditions: item.failure_conditions ?? [],
    evidence_slots: item.evidence_slots ?? [],
    formula_checks: item.formula_checks ?? [],
    expert_brief: getExpertBriefFromSnapshot(item.source_rule_snapshot) ?? buildExpertBriefFromStructured(item),
    reasoning_process: item.reasoning_process ?? {},
    ai_or_human_source: item.ai_or_human_source,
  };
}

function getReasoningString(reasoning: Record<string, unknown> | undefined, key: string): string {
  const reviewRule = reasoning?.review_rule;
  if (reviewRule && typeof reviewRule === 'object' && key in reviewRule) {
    const value = (reviewRule as Record<string, unknown>)[key];
    if (typeof value === 'string') return value;
  }
  const value = reasoning?.[key];
  return typeof value === 'string' ? value : '';
}

function findTopicRuleTemplate(topic: ReviewRuleTopic | undefined, ruleId: string): ReviewCheckItem | null {
  if (!topic || !ruleId) return null;
  const candidates = [
    ...(topic.rule_candidates ?? []),
    ...(topic.check_items ?? []),
    ...(topic.items ?? []).flatMap((item) => item.rules ?? []),
  ];
  return candidates.find((candidate) => candidate.rule_id === ruleId) ?? null;
}

function getTopicRuleOptions(topic?: ReviewRuleTopic): TopicRuleOption[] {
  if (!topic) return [];
  const options: TopicRuleOption[] = [];
  const seen = new Set<string>();

  for (const rule of topic.rule_candidates ?? []) {
    if (!rule.rule_id || seen.has(rule.rule_id)) continue;
    seen.add(rule.rule_id);
    options.push({
      rule_id: rule.rule_id,
      label: rule.rule_name || rule.review_sub_type || rule.rule_id,
    });
  }

  for (const item of topic.items ?? []) {
    for (const rule of item.rules ?? []) {
      if (!rule.rule_id || seen.has(rule.rule_id)) continue;
      seen.add(rule.rule_id);
      options.push({
        rule_id: rule.rule_id,
        label: rule.rule_name || rule.review_sub_type || rule.rule_id,
      });
    }
  }

  for (const checkItem of topic.check_items ?? []) {
    if (!checkItem.rule_id || seen.has(checkItem.rule_id)) continue;
    seen.add(checkItem.rule_id);
    options.push({
      rule_id: checkItem.rule_id,
      label: checkItem.rule_name || checkItem.review_sub_type || checkItem.rule_id,
    });
  }

  return options;
}

function checkItemSourceLabel(source: string): string {
  const labels: Record<string, string> = {
    configured_checklist: '配置项',
    rule_set: '规则集',
    planned_checklist: '计划项',
    planned: '计划项',
    issue: '问题',
    ai_issue: '问题',
    human_issue: '人工问题',
  };
  return labels[source] ?? source;
}

function getErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message;
  if (typeof err === 'object' && err !== null && 'message' in err) {
    const message = (err as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim()) return message;
  }
  return '未知错误';
}

function loadRuleTopics(sessionId: string) {
  return getReviewRuleTopics(sessionId);
}

function checkStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    failed: '错误',
    issue: '错误',
    pending: '待审',
    needs_review: '待核',
    passed: '通过',
    rejected: '驳回',
    disabled: '停用',
  };
  return labels[status] ?? status;
}

function findReviewRuleContext(
  topics: ReviewRuleTopic[],
  ruleId?: string,
  sourceIssueId?: string
): { topic: ReviewRuleTopic; item?: ReviewRuleItem; checkItem: ReviewCheckItem } | null {
  if (sourceIssueId) {
    for (const topic of topics) {
      const directItem = topic.check_items.find((candidate) => candidate.source_issue_id === sourceIssueId);
      if (directItem) return { topic, checkItem: directItem };
    }
  }

  if (!ruleId) {
    return null;
  }

  for (const topic of topics) {
    const directItem = topic.check_items.find((candidate) => candidate.rule_id === ruleId);
    if (directItem) return { topic, checkItem: directItem };
    const ruleCandidate = topic.rule_candidates?.find((candidate) => candidate.rule_id === ruleId);
    if (ruleCandidate) return { topic, checkItem: ruleCandidate };
    for (const item of topic.items ?? []) {
      const rule = item.rules.find((candidate) => candidate.rule_id === ruleId);
      if (rule) return { topic, item, checkItem: rule };
    }
  }
  return null;
}

function truncateText(value: unknown, maxLength = 96): string {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  if (text.length <= maxLength) return text;
  return `${text.slice(0, maxLength)}...`;
}

function toStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item ?? '').trim()).filter(Boolean) : [];
}

function toUnknownArray(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (value && typeof value === 'object') return [value];
  return [];
}

function toRecordArray(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
    : [];
}

function formatCompactJson(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function formatScore(value: unknown): string {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return '-';
  return numeric.toFixed(3);
}

function formatNullableNumber(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-';
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value);
  return Number.isInteger(numeric) ? String(numeric) : numeric.toFixed(2);
}

function getRetrievalContributionBadges(match: RetrievalMatch, fallbackIndex: number): RetrievalContributionBadge[] {
  const sourceRanks = match.source_ranks && typeof match.source_ranks === 'object' && !Array.isArray(match.source_ranks)
    ? match.source_ranks
    : {};
  const rawSources = Array.isArray(match.retrieval_sources) && match.retrieval_sources.length > 0
    ? match.retrieval_sources
    : inferRetrievalSources(match);
  const sources = orderRetrievalSources(rawSources);
  const primary = primaryRetrievalSource(match, sources, sourceRanks);
  const badges: RetrievalContributionBadge[] = [
    {
      key: 'primary',
      label: `主命中：${primary.label}`,
      className: primary.className,
    },
    {
      key: 'final',
      label: `最终排序 #${numberOrFallback(match.final_rank, fallbackIndex + 1)}`,
      className: 'bg-slate-100 text-slate-700 ring-slate-200',
    },
  ];

  for (const source of sources) {
    const rank = Number(sourceRanks[source] ?? match[`${source}_rank`]);
    const meta = retrievalSourceMeta(source);
    badges.push({
      key: source,
      label: Number.isFinite(rank) ? `${meta.secondaryLabel} #${rank}` : meta.secondaryLabel,
      className: meta.className,
    });
  }
  if (match.bm25_score !== undefined) {
    badges.push({
      key: 'bm25-score',
      label: `BM25分 ${formatScore(match.bm25_score)}`,
      className: 'bg-white text-amber-700 ring-amber-200',
    });
  }
  if (match.vector_score !== undefined) {
    badges.push({
      key: 'vector-score',
      label: `向量分 ${formatScore(match.vector_score)}`,
      className: 'bg-white text-blue-700 ring-blue-200',
    });
  }
  if (match.rerank_score !== undefined) {
    badges.push({
      key: 'rerank-score',
      label: `重排分 ${formatScore(match.rerank_score)}`,
      className: 'bg-white text-emerald-700 ring-emerald-200',
    });
  }
  return badges;
}

function primaryRetrievalSource(
  match: RetrievalMatch,
  sources: string[],
  sourceRanks: Record<string, unknown>
): { label: string; className: string } {
  const hasBm25 = sources.includes('bm25');
  const hasVector = sources.includes('vector');
  const hasNeighbor = sources.includes('neighbor');
  if (hasBm25 && hasVector) {
    const bm25Contribution = rrfContribution(sourceRanks.bm25 ?? match.bm25_rank);
    const vectorContribution = rrfContribution(sourceRanks.vector ?? match.vector_rank);
    if (bm25Contribution && vectorContribution) {
      const diff = Math.abs(bm25Contribution - vectorContribution);
      if (diff <= 0.0005) return primaryRetrievalMeta('hybrid');
      return bm25Contribution > vectorContribution ? primaryRetrievalMeta('bm25') : primaryRetrievalMeta('vector');
    }
    return primaryRetrievalMeta('hybrid');
  }
  if (hasBm25) return primaryRetrievalMeta('bm25');
  if (hasVector) return primaryRetrievalMeta('vector');
  if (hasNeighbor) return primaryRetrievalMeta('neighbor');
  return primaryRetrievalMeta('unknown');
}

function rrfContribution(rankValue: unknown): number | null {
  const rank = Number(rankValue);
  if (!Number.isFinite(rank) || rank <= 0) return null;
  return 1 / (60 + rank);
}

function primaryRetrievalMeta(source: string): { label: string; className: string } {
  const metas: Record<string, { label: string; className: string }> = {
    bm25: { label: 'BM25关键词召回', className: 'bg-amber-600 text-white ring-amber-700' },
    vector: { label: '向量语义召回', className: 'bg-blue-600 text-white ring-blue-700' },
    hybrid: { label: 'BM25+向量混合召回', className: 'bg-indigo-600 text-white ring-indigo-700' },
    neighbor: { label: '邻近扩展补充', className: 'bg-violet-600 text-white ring-violet-700' },
    unknown: { label: '未识别', className: 'bg-slate-500 text-white ring-slate-600' },
  };
  return metas[source] ?? metas.unknown;
}

function orderRetrievalSources(sources: string[]): string[] {
  const order = ['bm25', 'vector', 'neighbor', 'rerank'];
  return [...new Set(sources)].sort((a, b) => {
    const left = order.indexOf(a);
    const right = order.indexOf(b);
    return (left === -1 ? 99 : left) - (right === -1 ? 99 : right);
  });
}

function retrievalSourceMeta(source: string): { secondaryLabel: string; className: string } {
  const metas: Record<string, { secondaryLabel: string; className: string }> = {
    bm25: { secondaryLabel: '参与BM25', className: 'bg-amber-50 text-amber-800 ring-amber-200' },
    vector: { secondaryLabel: '参与向量', className: 'bg-blue-50 text-blue-800 ring-blue-200' },
    neighbor: { secondaryLabel: '邻近补充', className: 'bg-violet-50 text-violet-800 ring-violet-200' },
    rerank: { secondaryLabel: '排序重排', className: 'bg-emerald-50 text-emerald-800 ring-emerald-200' },
  };
  return metas[source] ?? { secondaryLabel: source, className: 'bg-slate-50 text-slate-700 ring-slate-200' };
}

function inferRetrievalSources(match: RetrievalMatch): string[] {
  const sources: string[] = [];
  if (match.bm25_score !== undefined || match.bm25_rank !== undefined) sources.push('bm25');
  if (match.rerank_score !== undefined || match.rerank_rank !== undefined) sources.push('rerank');
  if (match.vector_score !== undefined || match.vector_rank !== undefined) sources.push('vector');
  if (match.neighbor_of || match.neighbor_rank !== undefined) sources.push('neighbor');
  return sources;
}

function numberOrFallback(value: unknown, fallback: number): number {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
}

function statusClassName(status: unknown): string {
  if (status === 'pass' || status === 'passed') return 'bg-green-50 text-green-700';
  if (status === 'needs_review' || status === 'pending' || status === 'potential_issue') return 'bg-amber-50 text-amber-700';
  if (status === 'disabled') return 'bg-slate-100 text-slate-500';
  if (status === 'failed' || status === 'error' || status === 'issue') return 'bg-rose-50 text-rose-700';
  return 'bg-slate-100 text-slate-600';
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
          <Row label="问题摘要" value={truncateText(getIssueDisplayTitle(item), 60)} />
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
