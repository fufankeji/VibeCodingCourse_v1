import { useEffect, useState, type ReactNode } from 'react';
import { CheckCircle, Edit2, Loader2, SkipForward } from 'lucide-react';
import { listFields, verifyField } from '../../api/fields';
import { ConfidenceBadge } from '../../components/ConfidenceBadge';
import type { ExtractedField, VerificationStatus } from '../../types';

type EditableField = ExtractedField & { editValue?: string };

interface FieldsStagePanelProps {
  sessionId: string;
  readOnly: boolean;
}

export function FieldsStagePanel({ sessionId, readOnly }: FieldsStagePanelProps) {
  const [fields, setFields] = useState<EditableField[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [submittingFieldId, setSubmittingFieldId] = useState<string | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!sessionId) {
      setFields([]);
      setIsLoading(false);
      return;
    }

    let canceled = false;
    setIsLoading(true);
    setError('');

    listFields(sessionId)
      .then((res) => {
        if (canceled) return;
        setFields(res.items.map((field) => ({ ...field, editValue: field.field_value })));
      })
      .catch((err) => {
        if (!canceled) setError(err.message || '加载字段失败');
      })
      .finally(() => {
        if (!canceled) setIsLoading(false);
      });

    return () => {
      canceled = true;
    };
  }, [sessionId]);

  const handleAction = async (field: EditableField, action: VerificationStatus) => {
    if (readOnly || !sessionId || submittingFieldId) return;
    const verifiedValue = action === 'modified' ? field.editValue ?? field.field_value : field.field_value;
    const apiAction = action === 'confirmed' ? 'confirm' : action === 'modified' ? 'modify' : 'skip';

    setSubmittingFieldId(field.id);
    setError('');
    try {
      await verifyField(sessionId, field.id, { action: apiAction, verified_value: verifiedValue });
      setFields((prev) =>
        prev.map((item) =>
          item.id === field.id
            ? { ...item, field_value: verifiedValue, editValue: verifiedValue, verification_status: action }
            : item
        )
      );
    } catch (err: any) {
      setError(err.message || '字段核验失败');
    } finally {
      setSubmittingFieldId(null);
    }
  };

  if (isLoading) {
    return (
      <PanelFrame title="关键信息">
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          正在加载字段
        </div>
      </PanelFrame>
    );
  }

  return (
    <PanelFrame title="关键信息">
      {readOnly ? (
        <p className="mb-3 rounded-md bg-slate-50 p-2 text-xs text-slate-500">当前会话只读，字段不可修改。</p>
      ) : null}
      {error ? <p className="mb-3 rounded-md bg-red-50 p-2 text-sm text-red-700">{error}</p> : null}
      <div className="space-y-3">
        {fields.length ? (
          fields.map((field) => {
            const isSubmitting = submittingFieldId === field.id;
            return (
              <div key={field.id} className="rounded-md border border-slate-200 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-medium text-slate-900">{field.field_label || field.field_name}</p>
                      <StatusTag status={field.verification_status} />
                    </div>
                    <input
                      value={field.editValue ?? field.field_value}
                      disabled={readOnly || isSubmitting}
                      onChange={(event) =>
                        setFields((prev) =>
                          prev.map((item) =>
                            item.id === field.id ? { ...item, editValue: event.target.value } : item
                          )
                        )
                      }
                      className="mt-2 w-full rounded-md border border-slate-200 px-2 py-1 text-sm text-slate-800 disabled:bg-slate-50 disabled:text-slate-500"
                    />
                  </div>
                  <ConfidenceBadge score={field.confidence_score} needsVerification={field.needs_human_verification} />
                </div>
                <p className="mt-2 text-xs leading-5 text-slate-500">
                  第 {field.source_page_number || '-'} 页：{field.source_evidence_text || '暂无原文依据'}
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={readOnly || isSubmitting}
                    onClick={() => handleAction(field, 'confirmed')}
                    className="inline-flex items-center gap-1 rounded border border-green-200 px-2 py-1 text-xs text-green-700 hover:bg-green-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <CheckCircle className="h-3 w-3" />
                    确认
                  </button>
                  <button
                    type="button"
                    disabled={readOnly || isSubmitting}
                    onClick={() => handleAction(field, 'modified')}
                    className="inline-flex items-center gap-1 rounded border border-blue-200 px-2 py-1 text-xs text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <Edit2 className="h-3 w-3" />
                    保存修改
                  </button>
                  <button
                    type="button"
                    disabled={readOnly || isSubmitting}
                    onClick={() => handleAction(field, 'skipped')}
                    className="inline-flex items-center gap-1 rounded border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    <SkipForward className="h-3 w-3" />
                    跳过
                  </button>
                </div>
              </div>
            );
          })
        ) : (
          <p className="text-sm text-slate-500">暂无已抽取的关键信息。</p>
        )}
      </div>
    </PanelFrame>
  );
}

function PanelFrame({ title, children }: { title: string; children: ReactNode }) {
  return (
    <aside className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h2 className="mb-3 text-base font-semibold text-slate-950">{title}</h2>
      {children}
    </aside>
  );
}

function StatusTag({ status }: { status: VerificationStatus | string }) {
  const config: Record<string, { label: string; className: string }> = {
    unverified: { label: '待核对', className: 'bg-slate-100 text-slate-500' },
    confirmed: { label: '已确认', className: 'bg-green-100 text-green-700' },
    verified: { label: '已确认', className: 'bg-green-100 text-green-700' },
    modified: { label: '已修改', className: 'bg-blue-100 text-blue-700' },
    skipped: { label: '已跳过', className: 'bg-slate-100 text-slate-500' },
  };
  const item = config[status] ?? config.unverified;
  return <span className={`rounded px-1.5 py-0.5 text-xs ${item.className}`}>{item.label}</span>;
}
