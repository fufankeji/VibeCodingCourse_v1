import { Check, AlertTriangle, Loader2 } from 'lucide-react';
import type { SessionState } from '../types';

interface WorkflowStatusBarProps {
  sessionState: SessionState;
  hitlSubtype?: string | null;
  /** scanning 是后端复用状态：确认页代表关键信息确认，扫描页代表规则审查路由。 */
  scanningStarted?: boolean;
}

const NODES = [
  { id: 'parse', label: '文件解析' },
  { id: 'pipeline', label: '清洗与向量审查' },
  { id: 'fields', label: '关键信息确认' },
  { id: 'routing', label: '规则审查路由' },
  { id: 'review', label: '人工复核' },
  { id: 'report', label: '报告生成' },
];

/**
 * WorkflowStatusBar — 工作流状态进度条
 * 高度固定 64px，挂载于 GlobalNav 正下方。
 * 节点按当前实现链路展示，不再沿用旧 PRD 的“AI 扫描/分级路由”固定拆法。
 */
export function WorkflowStatusBar({ sessionState, hitlSubtype, scanningStarted }: WorkflowStatusBarProps) {
  const getNodeStatus = (nodeId: string): 'completed' | 'active' | 'interrupted' | 'loading' | 'pending' => {
    switch (sessionState) {
      case 'parsing':
        if (nodeId === 'parse') return 'active';
        return 'pending';
      case 'parsed':
        if (nodeId === 'parse') return 'completed';
        if (nodeId === 'pipeline') return 'active';
        return 'pending';
      case 'aborted':
        if (nodeId === 'parse') return 'interrupted';
        return 'pending';
      case 'scanning':
        if (['parse', 'pipeline'].includes(nodeId)) return 'completed';
        if (nodeId === 'fields') return scanningStarted ? 'completed' : 'active';
        if (nodeId === 'routing') return scanningStarted ? 'active' : 'pending';
        return 'pending';
      case 'hitl_field_verify':
        if (['parse', 'pipeline'].includes(nodeId)) return 'completed';
        if (nodeId === 'fields') return 'active';
        return 'pending';
      case 'hitl_high_risk':
      case 'hitl_medium_confirm':
        if (['parse', 'pipeline', 'fields', 'routing'].includes(nodeId)) return 'completed';
        if (nodeId === 'review') return 'interrupted';
        return 'pending';
      case 'hitl_pending':
        if (['parse', 'pipeline', 'fields', 'routing'].includes(nodeId)) return 'completed';
        if (nodeId === 'review') return 'interrupted';
        return 'pending';
      case 'completed':
        if (['parse', 'pipeline', 'fields', 'routing', 'review'].includes(nodeId)) return 'completed';
        if (nodeId === 'report') return 'loading';
        return 'pending';
      case 'report_ready':
        return 'completed';
      default:
        return 'pending';
    }
  };

  return (
    <div
      className="fixed top-14 left-0 right-0 z-40 bg-white border-b border-gray-200 flex items-center justify-center shadow-sm"
      style={{ height: 64 }}
    >
      <div className="flex w-full items-center justify-center gap-0 overflow-hidden px-2 sm:w-auto sm:px-0">
        {NODES.map((node, idx) => {
          const status = getNodeStatus(node.id);
          return (
            <div key={node.id} className="flex items-center">
              {/* Node */}
              <div className="flex flex-col items-center">
                <NodeDot status={status} label={node.label} />
              </div>
              {/* Connector */}
              {idx < NODES.length - 1 && (
                <div
                  className={`mx-0.5 h-0.5 w-4 sm:mx-1 sm:w-16 ${
                    getNodeStatus(NODES[idx + 1].id) !== 'pending' || status === 'completed'
                      ? 'bg-blue-300'
                      : 'bg-gray-200'
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function NodeDot({
  status,
  label,
}: {
  status: 'completed' | 'active' | 'interrupted' | 'loading' | 'pending';
  label: string;
}) {
  const dotClass = {
    completed: 'bg-blue-500 border-blue-500',
    active: 'bg-blue-600 border-blue-600 ring-2 ring-blue-200',
    interrupted: 'bg-orange-500 border-orange-500 ring-2 ring-orange-200',
    loading: 'bg-blue-200 border-blue-300',
    pending: 'bg-white border-gray-300',
  }[status];

  const textClass = {
    completed: 'text-blue-600',
    active: 'text-blue-700',
    interrupted: 'text-orange-600',
    loading: 'text-blue-500',
    pending: 'text-gray-400',
  }[status];

  return (
    <div className="flex min-w-10 flex-col items-center gap-1 sm:min-w-[72px]">
      <div
        className={`w-7 h-7 rounded-full border-2 flex items-center justify-center transition-all ${dotClass}`}
        title={status === 'interrupted' ? '流程已暂停 - 等待人工操作' : undefined}
      >
        {status === 'completed' && <Check className="w-3.5 h-3.5 text-white" strokeWidth={3} />}
        {status === 'interrupted' && <AlertTriangle className="w-3.5 h-3.5 text-white" />}
        {status === 'loading' && <Loader2 className="w-3.5 h-3.5 text-blue-500 animate-spin" />}
        {status === 'active' && <div className="w-2 h-2 rounded-full bg-white" />}
      </div>
      <span className={`hidden text-xs whitespace-nowrap sm:inline ${textClass}`}>{label}</span>
    </div>
  );
}
