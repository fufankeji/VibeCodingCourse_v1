interface StateBadgeProps {
  state: string;
  className?: string;
}

const STATE_CONFIG: Record<string, { label: string; className: string }> = {
  processing: { label: '处理中', className: 'bg-slate-100 text-slate-600 border border-slate-300' },
  parsing: { label: '解析中', className: 'bg-gray-100 text-gray-600 border border-gray-300' },
  scanning: { label: '规则审查中', className: 'bg-blue-100 text-blue-700 border border-blue-300' },
  hitl_field_verify: { label: '字段核对', className: 'bg-sky-100 text-sky-700 border border-sky-300' },
  hitl_pending: { label: '待人工审核', className: 'bg-orange-100 text-orange-700 border border-orange-300' },
  hitl_high_risk: { label: '高风险待审', className: 'bg-red-100 text-red-700 border border-red-300' },
  hitl_medium_confirm: { label: '中风险复核', className: 'bg-amber-100 text-amber-700 border border-amber-300' },
  completed: { label: '生成报告中', className: 'bg-indigo-100 text-indigo-700 border border-indigo-300' },
  report_ready: { label: '已完成', className: 'bg-green-100 text-green-700 border border-green-300' },
  aborted: { label: '已中止', className: 'bg-red-100 text-red-600 border border-red-300' },
};

/**
 * StateBadge - 状态标签
 * R11: 颜色映射严格基于后端返回的 ReviewSession.state 字段，前端不自行推断状态
 */
export function StateBadge({ state, className = '' }: StateBadgeProps) {
  const config = STATE_CONFIG[state] ?? STATE_CONFIG.processing;
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs ${config.className} ${className}`}>
      {config.label}
    </span>
  );
}
