import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle, Loader2, XCircle } from 'lucide-react';
import { listItems, submitDecision } from '../../api/items';
import { RiskLevelBadge } from '../../components/RiskLevelBadge';
import { SourceBadge } from '../../components/SourceBadge';
import type { HumanDecision, ReviewItem, RiskLevel } from '../../types';

export function ReviewIssuePanel({
  sessionId,
  readOnly,
  onEvidencePage,
}: {
  sessionId: string;
  readOnly: boolean;
  onEvidencePage: (page: number) => void;
}) {
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  const [humanNote, setHumanNote] = useState('');
  const [hasReadEvidence, setHasReadEvidence] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!sessionId) {
      setItems([]);
      setActiveItemId(null);
      setIsLoading(false);
      return;
    }

    let canceled = false;
    setIsLoading(true);
    setError('');

    listItems(sessionId, { limit: 100 })
      .then((res) => {
        if (canceled) return;
        setItems(res.items);
        setActiveItemId(
          res.items.find((item) => item.human_decision === 'pending')?.id ?? res.items[0]?.id ?? null
        );
      })
      .catch((err) => {
        if (!canceled) setError(err.message || '加载审查项失败');
      })
      .finally(() => {
        if (!canceled) setIsLoading(false);
      });

    return () => {
      canceled = true;
    };
  }, [sessionId]);

  const activeItem = items.find((item) => item.id === activeItemId) ?? null;

  useEffect(() => {
    const page = activeItem?.clause_location?.page_number || activeItem?.risk_evidence?.[0]?.page_number;
    if (page) onEvidencePage(page);
    setHumanNote(activeItem?.human_note ?? '');
    setHasReadEvidence(false);
    if (!activeItem) return;
    const timer = window.setTimeout(() => setHasReadEvidence(true), 2000);
    return () => window.clearTimeout(timer);
  }, [activeItem?.id, activeItem?.clause_location?.page_number, activeItem?.human_note, onEvidencePage]);

  const decide = async (decision: HumanDecision) => {
    if (!activeItem || readOnly || isSubmitting || !canSubmitDecision(humanNote, hasReadEvidence)) return;
    setIsSubmitting(true);
    setError('');
    try {
      const result = await submitDecision(sessionId, activeItem.id, {
        decision,
        human_note: humanNote,
        edited_risk_level: decision === 'edit' ? (activeItem.risk_level as RiskLevel) : null,
        edited_finding: decision === 'edit' ? activeItem.ai_finding : null,
        is_false_positive: decision === 'reject',
        client_submitted_at: new Date().toISOString(),
      });

      setItems((prev) =>
        prev.map((item) =>
          item.id === activeItem.id
            ? {
                ...item,
                human_decision: decision,
                human_note: humanNote,
                human_edited_risk_level: decision === 'edit' ? activeItem.risk_level : null,
                human_edited_finding: decision === 'edit' ? activeItem.ai_finding : null,
                is_false_positive: decision === 'reject',
                decided_at: result.decided_at,
              }
            : item
        )
      );
    } catch (err: any) {
      setError(err.message || '提交复核决策失败');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <aside className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-slate-950">人工复核</h2>
          <p className="mt-1 text-xs text-slate-500">最小可用复核：选择审查项并提交人工决策。</p>
        </div>
        {isLoading ? <Loader2 className="h-5 w-5 animate-spin text-slate-400" /> : null}
      </div>

      {readOnly ? (
        <p className="mt-3 rounded-md bg-slate-50 p-2 text-xs text-slate-500">当前会话只读，不能提交复核决策。</p>
      ) : null}
      {error ? <p className="mt-3 rounded-md bg-red-50 p-2 text-sm text-red-700">{error}</p> : null}
      {!isLoading && items.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">尚未生成审查项。请先查看清洗与规则审查状态。</p>
      ) : null}

      <div className="mt-4 max-h-72 space-y-2 overflow-auto">
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setActiveItemId(item.id)}
            className={`w-full rounded-md border p-3 text-left ${
              item.id === activeItemId ? 'border-blue-300 bg-blue-50' : 'border-slate-200 bg-white hover:bg-slate-50'
            }`}
          >
            <div className="flex flex-wrap items-center gap-2">
              <RiskLevelBadge level={item.risk_level} />
              <SourceBadge sourceType={item.source_type} />
              <DecisionTag decision={item.human_decision} />
            </div>
            <p className="mt-2 line-clamp-2 text-sm text-slate-700">{item.ai_finding}</p>
          </button>
        ))}
      </div>

      {activeItem ? (
        <div className="mt-4 rounded-md border border-slate-200 p-3">
          <div className="mb-2 flex items-center gap-2 text-amber-700">
            <AlertTriangle className="h-4 w-4" />
            <span className="text-sm font-medium">{activeItem.risk_category}</span>
          </div>
          <p className="text-sm leading-6 text-slate-800">{activeItem.ai_finding}</p>
          <p className="mt-2 text-xs leading-5 text-slate-500">{getReasoningSummary(activeItem)}</p>
          <EvidenceList item={activeItem} />
          <textarea
            disabled={readOnly || isSubmitting}
            value={humanNote}
            onChange={(event) => setHumanNote(event.target.value)}
            className="mt-3 min-h-20 w-full rounded-md border border-slate-200 p-2 text-sm text-slate-800 disabled:bg-slate-50 disabled:text-slate-500"
            placeholder="填写人工复核意见"
          />
          <p className="mt-1 text-xs text-slate-500">
            {hasReadEvidence ? '已进入证据阅读状态' : '请先查看证据，2 秒后可提交'} ·
            {humanNote.trim().length >= 10 ? ` 已满足 10 字要求` : ` 还需 ${Math.max(0, 10 - humanNote.trim().length)} 字`}
          </p>
          <div className="mt-3 grid grid-cols-3 gap-2">
            <button
              type="button"
              disabled={readOnly || isSubmitting || !canSubmitDecision(humanNote, hasReadEvidence)}
              onClick={() => decide('approve')}
              className="inline-flex items-center justify-center gap-1 rounded-md bg-green-600 px-2 py-2 text-xs text-white hover:bg-green-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <CheckCircle className="h-3 w-3" />
              通过
            </button>
            <button
              type="button"
              disabled={readOnly || isSubmitting || !canSubmitDecision(humanNote, hasReadEvidence)}
              onClick={() => decide('edit')}
              className="inline-flex items-center justify-center gap-1 rounded-md bg-blue-600 px-2 py-2 text-xs text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              修正
            </button>
            <button
              type="button"
              disabled={readOnly || isSubmitting || !canSubmitDecision(humanNote, hasReadEvidence)}
              onClick={() => decide('reject')}
              className="inline-flex items-center justify-center gap-1 rounded-md bg-red-600 px-2 py-2 text-xs text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <XCircle className="h-3 w-3" />
              误报
            </button>
          </div>
        </div>
      ) : null}
    </aside>
  );
}

function canSubmitDecision(humanNote: string, hasReadEvidence: boolean): boolean {
  return hasReadEvidence && humanNote.trim().length >= 10;
}

function getReasoningSummary(item: ReviewItem): string {
  const result = item.review_result;
  const summary = String(result?.reasoning_summary || result?.issue_desc || '').trim();
  if (summary) return truncateText(summary, 240);
  try {
    const parsed = JSON.parse(item.ai_reasoning);
    const fields = [
      parsed?.rule_name,
      parsed?.review_status,
      parsed?.actual_value,
      parsed?.suggested_revision,
      parsed?.llm_error?.error,
    ]
      .map((value) => String(value || '').trim())
      .filter(Boolean);
    if (fields.length > 0) return truncateText(fields.join('；'), 240);
  } catch {
    // Raw string fallback below.
  }
  return truncateText(item.ai_reasoning || '暂无推理摘要', 240);
}

function truncateText(value: string, maxLength: number): string {
  const normalized = value.replace(/\s+/g, ' ').trim();
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength)}...`;
}

function DecisionTag({ decision }: { decision: HumanDecision }) {
  const config: Record<HumanDecision, { label: string; className: string }> = {
    pending: { label: '待复核', className: 'bg-slate-100 text-slate-500' },
    approve: { label: '已通过', className: 'bg-green-100 text-green-700' },
    edit: { label: '已修正', className: 'bg-blue-100 text-blue-700' },
    reject: { label: '已误报', className: 'bg-red-100 text-red-700' },
  };
  const item = config[decision] ?? config.pending;
  return <span className={`rounded px-1.5 py-0.5 text-xs ${item.className}`}>{item.label}</span>;
}

function EvidenceList({ item }: { item: ReviewItem }) {
  const evidence = item.risk_evidence.slice(0, 2);
  if (evidence.length === 0) return null;

  return (
    <div className="mt-3 space-y-2">
      {evidence.map((entry) => (
        <p key={entry.id} className="rounded-md bg-slate-50 p-2 text-xs leading-5 text-slate-500">
          第 {entry.page_number || '-'} 页：{truncateText(entry.evidence_text, 220)}
        </p>
      ))}
    </div>
  );
}
