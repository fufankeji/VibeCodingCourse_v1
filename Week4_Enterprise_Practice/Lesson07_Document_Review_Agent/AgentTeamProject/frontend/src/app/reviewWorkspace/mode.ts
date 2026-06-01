import type { SessionResponse } from '../api/sessions';
import type { ReviewWorkspaceMode } from './types';

export function modeFromPath(pathname: string): ReviewWorkspaceMode {
  if (pathname.endsWith('/fields')) return 'fields';
  if (pathname.endsWith('/scanning')) return 'scanning';
  if (pathname.endsWith('/review')) return 'review';
  return 'document';
}

export function modeTitle(mode: ReviewWorkspaceMode): string {
  if (mode === 'fields') return '关键信息';
  if (mode === 'scanning') return '清洗与规则审查';
  if (mode === 'review') return '人工复核';
  return '解析文档';
}

export function modeDescription(mode: ReviewWorkspaceMode): string {
  if (mode === 'fields') return '查看并核对从文档中抽取出的项目名称、面积、土石方、投资等关键信息。';
  if (mode === 'scanning') return '查看数据清洗、向量索引、RAG 检索和规则判定的真实后端状态。';
  if (mode === 'review') return '查看规则命中、证据来源和人工复核动作。';
  return '查看原始 PDF 和 MinerU 已生成的结构化解析结果。';
}

export function isReadOnlySession(session: SessionResponse | null): boolean {
  return Boolean(session?.read_only || session?.state === 'aborted');
}

export function canStartReview(session: SessionResponse | null): boolean {
  return Boolean(session && !isReadOnlySession(session) && session.state === 'parsed');
}

export function canRestartReview(session: SessionResponse | null, hasFailure: boolean): boolean {
  if (!session || isReadOnlySession(session)) return false;
  return session.state === 'parsed' || (session.state === 'scanning' && hasFailure);
}

export function canReviewItems(session: SessionResponse | null): boolean {
  if (!session || isReadOnlySession(session)) return false;
  return session.state === 'hitl_pending' || session.state === 'hitl_high_risk' || session.state === 'hitl_medium_confirm';
}
