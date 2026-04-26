import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router';
import { CheckCircle, Edit2, SkipForward, ChevronDown, ChevronUp, Zap, ArrowLeft, Loader2 } from 'lucide-react';
import { GlobalNav } from '../components/GlobalNav';
import { WorkflowStatusBar } from '../components/WorkflowStatusBar';
import { ConfidenceBadge } from '../components/ConfidenceBadge';
import { listFields, verifyField } from '../api/fields';
import type { ExtractedField, VerificationStatus } from '../types';

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
  excavation_volume: '挖方',
  fill_volume: '填方',
  borrow_volume: '借方',
  spoil_volume: '弃方',
  topsoil_stripping: '表土剥离',
  topsoil_preservation: '表土保存',
  topsoil_backfill: '表土回覆',
  spoil_ground: '弃渣场',
  spoil_area: '弃渣场',
  borrow_ground: '取土场',
  borrow_area: '取土场',
  construction_road: '施工道路',
  prevention_measures: '防治措施',
  investment_estimate: '投资估算',
};

/**
 * FieldVerificationPage — P06 字段核对页
 * GET /sessions/{session_id}/fields — 已开发
 * PATCH /sessions/{session_id}/fields/{field_id} — 已开发（action: confirm/modify/skip）
 * R08: 置信度颜色严格来自 confidence_score 字段
 */
export function FieldVerificationPage() {
  const { id: sessionId } = useParams();
  const navigate = useNavigate();

  const [fields, setFields] = useState<(ExtractedField & { editValue?: string; expanded?: boolean })[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [isStartingScanning, setIsStartingScanning] = useState(false);

  // Load fields from backend
  useEffect(() => {
    if (!sessionId) return;
    setIsLoading(true);
    listFields(sessionId)
      .then((res) => {
        setFields(res.items.map((f) => ({ ...f, editValue: f.field_value, expanded: false })));
      })
      .catch((err) => setLoadError(err.message || '加载字段失败'))
      .finally(() => setIsLoading(false));
  }, [sessionId]);

  const lowConfidenceFields = fields.filter((f) => f.needs_human_verification && f.verification_status === 'unverified');

  const handleAction = async (fieldId: string, action: VerificationStatus, newValue?: string) => {
    if (!sessionId) return;
    // Optimistic update
    setFields((prev) =>
      prev.map((f) =>
        f.id === fieldId
          ? {
              ...f,
              verification_status: action === 'modified' ? 'modified' : action,
              field_value: action === 'modified' && newValue ? newValue : f.field_value,
              expanded: false,
            }
          : f
      )
    );
    try {
      const apiAction = action === 'confirmed' ? 'confirm' : action === 'modified' ? 'modify' : 'skip';
      const field = fields.find((f) => f.id === fieldId);
      await verifyField(sessionId, fieldId, {
        action: apiAction,
        verified_value: action === 'modified' && newValue ? newValue : field?.field_value ?? '',
      });
    } catch (err: any) {
      console.error('字段核验失败:', err.message);
    }
  };

  const handleStartScan = async () => {
    setIsStartingScanning(true);
    await new Promise((r) => setTimeout(r, 800));
    navigate(`/contracts/${sessionId}/scanning`);
  };

  const toggleExpand = (fieldId: string) => {
    setFields((prev) => prev.map((f) => (f.id === fieldId ? { ...f, expanded: !f.expanded } : f)));
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <GlobalNav />
      <WorkflowStatusBar sessionState="scanning" scanningStarted={false} />
      <div style={{ paddingTop: 78 }}>
        <div className="max-w-3xl mx-auto px-6 py-6">
          {/* Header */}
          <div className="mb-5">
            <p className="text-xs text-gray-400 mb-1">session_id: {sessionId}</p>
            <h1 className="text-gray-900" style={{ fontSize: 20, fontWeight: 700 }}>字段核对</h1>
            <p className="text-sm text-gray-500 mt-1">
              请核对 AI 提取的水保方案结构化字段，确认无误后可启动规则审查
            </p>
          </div>

          {/* Loading State */}
          {isLoading && (
            <div className="flex items-center justify-center py-16 text-gray-400">
              <Loader2 className="w-6 h-6 animate-spin mr-2" /> 正在加载字段数据…
            </div>
          )}

          {/* Error State */}
          {loadError && (
            <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 mb-5 text-sm text-red-600">
              加载失败：{loadError}
            </div>
          )}

          {/* Low Confidence Summary */}
          {lowConfidenceFields.length > 0 && (
            <div className="bg-orange-50 border border-orange-200 rounded-xl px-4 py-3 mb-5 flex items-start gap-2">
              <span className="text-orange-500 text-base mt-0.5">⚠</span>
              <div className="text-sm text-orange-700">
                <span style={{ fontWeight: 500 }}>以下 {lowConfidenceFields.length} 个字段置信度较低，请重点核对：</span>
                <span className="ml-2 text-orange-600">{lowConfidenceFields.map((f) => FIELD_LABEL[f.field_name] ?? f.field_name).join('、')}</span>
              </div>
            </div>
          )}

          {/* Field Cards */}
          <div className="space-y-3 mb-6">
            {fields.map((field) => {
              const isVerified = field.verification_status !== 'unverified';
              const needsCheck = field.needs_human_verification;
              const borderColor = needsCheck && !isVerified
                ? 'border-orange-300 bg-orange-50/30'
                : isVerified
                ? 'border-green-200 bg-green-50/10'
                : 'border-gray-200';

              return (
                <div key={field.id} className={`bg-white rounded-xl border ${borderColor} overflow-hidden`}>
                  <div className="px-4 py-3 flex items-center justify-between">
                    <div className="flex items-center gap-3 flex-1 min-w-0">
                      <div className="min-w-20">
                        <span className="text-sm text-gray-700" style={{ fontWeight: 500 }}>
                          {FIELD_LABEL[field.field_name] ?? field.field_name}
                        </span>
                        {needsCheck && !isVerified && (
                          <span className="ml-1.5 text-xs text-orange-500 bg-orange-100 px-1.5 rounded">需核对</span>
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        {field.expanded && !isVerified ? (
                          <input
                            type="text"
                            value={field.editValue ?? field.field_value}
                            onChange={(e) =>
                              setFields((prev) => prev.map((f) => f.id === field.id ? { ...f, editValue: e.target.value } : f))
                            }
                            className="w-full text-sm border border-blue-300 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-blue-400"
                          />
                        ) : (
                          <span className="text-sm text-gray-800 truncate block">{field.field_value}</span>
                        )}
                      </div>
                      <ConfidenceBadge score={field.confidence_score} needsVerification={field.needs_human_verification} />
                    </div>

                    <div className="flex items-center gap-1.5 ml-3 shrink-0">
                      {isVerified ? (
                        <StatusTag status={field.verification_status} />
                      ) : (
                        <>
                          <button
                            onClick={() => handleAction(field.id, 'confirmed')}
                            title="确认（confirm）"
                            className="flex items-center gap-1 text-xs text-green-600 hover:bg-green-50 border border-green-200 px-2 py-1 rounded transition-colors"
                          >
                            <CheckCircle className="w-3 h-3" /> 确认
                          </button>
                          <button
                            onClick={() => toggleExpand(field.id)}
                            title="修改（modify）"
                            className="flex items-center gap-1 text-xs text-blue-600 hover:bg-blue-50 border border-blue-200 px-2 py-1 rounded transition-colors"
                          >
                            <Edit2 className="w-3 h-3" />
                            {field.expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                          </button>
                          {field.expanded && (
                            <button
                              onClick={() => handleAction(field.id, 'modified', field.editValue)}
                              className="text-xs text-white bg-blue-600 hover:bg-blue-700 px-2 py-1 rounded transition-colors"
                            >
                              提交修改
                            </button>
                          )}
                          <button
                            onClick={() => handleAction(field.id, 'skipped')}
                            title="跳过（skip）"
                            className="flex items-center gap-1 text-xs text-gray-500 hover:bg-gray-50 border border-gray-200 px-2 py-1 rounded transition-colors"
                          >
                            <SkipForward className="w-3 h-3" /> 跳过
                          </button>
                        </>
                      )}
                    </div>
                  </div>

                  {/* Source Evidence */}
                  <div className="px-4 py-2 bg-gray-50 border-t border-gray-100 text-xs text-gray-400">
                    原文依据（第 {field.source_page_number} 页）：
                    <span className="text-gray-500 ml-1">"{field.source_evidence_text}"</span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Action Area */}
          <div className="flex gap-3">
            <button
              onClick={handleStartScan}
              disabled={isStartingScanning}
              className="flex-1 flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white py-3 rounded-xl text-sm transition-colors"
              style={{ fontWeight: 500 }}
            >
              <Zap className="w-4 h-4" />
              {isStartingScanning ? 'AI 审查启动中…' : '开始 AI 规则审查'}
            </button>
            <button
              onClick={() => navigate('/contracts')}
              className="flex items-center gap-2 border border-gray-200 text-gray-600 px-5 py-3 rounded-xl text-sm hover:bg-gray-50 transition-colors"
            >
              <ArrowLeft className="w-4 h-4" /> 返回
            </button>
          </div>

          {/* API Info */}
          <div className="mt-4 bg-blue-50 border border-blue-100 rounded-lg px-3 py-2">
            <p className="text-xs text-blue-600">
              <span style={{ fontWeight: 600 }}>API：</span>
              GET /sessions/{sessionId}/fields · PATCH /sessions/{sessionId}/fields/&#123;field_id&#125;
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatusTag({ status }: { status: VerificationStatus }) {
  const config = {
    confirmed: { label: '已确认', className: 'bg-green-100 text-green-700' },
    modified: { label: '已修改', className: 'bg-blue-100 text-blue-700' },
    skipped: { label: '已跳过', className: 'bg-gray-100 text-gray-500' },
    unverified: { label: '待核对', className: 'bg-orange-100 text-orange-600' },
  }[status] ?? { label: '待核对', className: 'bg-gray-100 text-gray-500' };

  return <span className={`text-xs px-2 py-0.5 rounded ${config.className}`}>{config.label}</span>;
}
