import { useEffect, useMemo, useState } from 'react';
import { CheckCircle2, Loader2 } from 'lucide-react';
import { listFields } from '../api/fields';
import { getReviewPipelineStatus } from '../api/sessions';
import type { ReviewPipelineStatusResponse } from '../api/sessions';
import type { ExtractedField } from '../types';

const FIELD_LABEL: Record<string, string> = {
  project_name: '项目名称',
  construction_unit: '建设单位',
  project_location: '建设地点',
  construction_location: '建设地点',
  construction_nature: '建设性质',
  project_nature: '建设性质',
  key_prevention_or_control_area: '重点防治区属性',
  disturbed_area: '扰动地表面积',
  occupied_area: '占地面积',
  land_area: '占地面积',
  prevention_responsibility_area: '防治责任范围面积',
  zone_area: '分区面积',
  excavation_volume: '挖方',
  fill_volume: '填方',
  borrow_volume: '借方',
  spoil_volume: '弃方',
  comprehensive_utilization: '综合利用',
  spoil_destination: '弃方去向',
  topsoil_stripping: '表土剥离',
  topsoil_preservation: '表土保存',
  topsoil_backfill: '表土回覆',
  temp_soil_stockpile: '临时堆土区',
  spoil_ground: '弃渣场',
  spoil_area: '弃渣场',
  borrow_ground: '取土场',
  borrow_area: '取土场',
  construction_road: '施工道路',
  prevention_measures: '防治措施',
  monitoring: '监测',
  schedule_arrangement: '时序安排',
  investment_estimate: '投资估算',
};

const STATUS_LABEL: Record<string, string> = {
  confirmed: '已确认',
  verified: '已确认',
  modified: '已修正',
  skipped: '已跳过',
  unverified: '待确认',
};

interface ExtractedFieldsSummaryProps {
  sessionId?: string;
  className?: string;
  limit?: number;
  dense?: boolean;
}

export function ExtractedFieldsSummary({
  sessionId,
  className = '',
  limit = 12,
  dense = false,
}: ExtractedFieldsSummaryProps) {
  const [fields, setFields] = useState<ExtractedField[]>([]);
  const [pipelineStatus, setPipelineStatus] = useState<ReviewPipelineStatusResponse | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!sessionId) return;
    setIsLoading(true);
    Promise.allSettled([listFields(sessionId), getReviewPipelineStatus(sessionId)])
      .then(([fieldsResult, statusResult]) => {
        if (statusResult.status === 'fulfilled') {
          setPipelineStatus(statusResult.value);
        } else {
          setPipelineStatus(null);
        }
        if (fieldsResult.status !== 'fulfilled') {
          throw fieldsResult.reason;
        }
        const res = fieldsResult.value;
        setFields(res.items);
        setError('');
      })
      .catch((err) => {
        setFields([]);
        setError(err.message || '关键信息读取失败');
      })
      .finally(() => setIsLoading(false));
  }, [sessionId]);

  const visibleFields = useMemo(
    () => fields.filter((field) => String(field.field_value || '').trim()).slice(0, limit),
    [fields, limit]
  );
  const confirmedCount = fields.filter((field) => ['confirmed', 'verified', 'modified', 'skipped'].includes(field.verification_status)).length;
  const emptyMessage = useMemo(() => {
    const stages = pipelineStatus?.stages ?? [];
    const byId = new Map(stages.map((stage) => [stage.id, stage]));
    const extracted = byId.get('extracted_fields');
    const facts = byId.get('langextract_facts');
    const dbItems = byId.get('review_items_db');
    if (extracted?.artifact_exists && (extracted.item_count ?? 0) > 0) {
      return '字段抽取产物已生成，但尚未写入关键信息确认表。请等待当前审查请求完成后刷新。';
    }
    if (extracted?.status === 'running' || facts?.status === 'running') {
      return '正在抽取关键信息，当前还没有可确认的字段。';
    }
    if (dbItems && (dbItems.item_count ?? 0) > 0 && fields.length === 0) {
      return '后端已有审查项，但关键信息确认表为空；这通常表示字段写入阶段未完成或失败。';
    }
    return '关键信息还没有生成。需要先完成“清洗与向量审查”，字段写入后这里才会展示。';
  }, [fields.length, pipelineStatus]);

  return (
    <section className={`rounded-lg border border-slate-200 bg-white shadow-sm ${dense ? 'p-3' : 'p-4'} ${className}`}>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-sm font-semibold text-slate-950">已抽取关键信息</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            后续规则审查、人工复核和报告生成都会复用这些结构化信息。
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2 rounded-full bg-slate-50 px-2.5 py-1 text-xs text-slate-600">
          <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
          {confirmedCount}/{fields.length || 0} 已确认
        </div>
      </div>

      {isLoading ? (
        <div className="mt-3 flex items-center gap-2 text-sm text-slate-500">
          <Loader2 className="h-4 w-4 animate-spin" />
          正在读取关键信息
        </div>
      ) : error ? (
        <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
          {error}
        </div>
      ) : visibleFields.length === 0 ? (
        <div className="mt-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
          {emptyMessage}
        </div>
      ) : (
        <div className={`mt-3 grid gap-2 ${dense ? 'sm:grid-cols-3 xl:grid-cols-4' : 'sm:grid-cols-2'}`}>
          {visibleFields.map((field) => (
            <div key={field.id} className="min-w-0 rounded-md border border-slate-100 bg-slate-50 px-3 py-2">
              <div className="flex items-center justify-between gap-2">
                <p className="truncate text-xs text-slate-500">{FIELD_LABEL[field.field_name] || field.field_name}</p>
                <span className="shrink-0 rounded-full bg-white px-1.5 py-0.5 text-[10px] text-slate-500">
                  {STATUS_LABEL[field.verification_status] || field.verification_status}
                </span>
              </div>
              <p className="mt-1 line-clamp-2 text-sm font-medium leading-5 text-slate-900">
                {field.field_value || '-'}
              </p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
