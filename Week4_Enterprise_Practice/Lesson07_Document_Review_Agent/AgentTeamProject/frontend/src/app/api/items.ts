import { apiClient } from './client';
import type { ReviewItem } from '../types';

/** Backend returns a flat ReviewItem without nested clause_location/risk_evidence */
interface BackendReviewItem {
  id: string;
  session_id: string;
  clause_text: string;
  page_number: number;
  paragraph_index: number;
  highlight_anchor: string;
  char_offset_start: number;
  char_offset_end: number;
  risk_level: string;
  confidence_score: number;
  source_type: string;
  risk_category: string;
  ai_finding: string;
  ai_reasoning: string;
  evidence_slot_package?: Record<string, unknown> | null;
  formula_check_results?: Record<string, unknown> | null;
  earthwork_audit_results?: Record<string, unknown> | null;
  project_composition_consistency?: Record<string, unknown> | null;
  review_status?: string | null;
  conclusion_type?: string | null;
  suggested_revision: string | null;
  human_decision: string;
  human_note: string | null;
  human_edited_risk_level: string | null;
  human_edited_finding: string | null;
  is_false_positive: boolean;
  decided_by: string | null;
  decided_at: string | null;
  created_at: string;
  updated_at: string;
}

/** Map backend decision values back to frontend HumanDecision type */
function mapDecision(raw: string): string {
  const map: Record<string, string> = {
    confirmed: 'approve',
    rejected: 'reject',
    false_positive: 'reject',
  };
  return map[raw] ?? raw; // 'pending', 'approve', 'edit' pass through unchanged
}

/** Transform flat backend item to nested frontend structure */
function transformItem(raw: BackendReviewItem): ReviewItem {
  return {
    id: raw.id,
    session_id: raw.session_id,
    risk_level: raw.risk_level as any,
    confidence_score: raw.confidence_score,
    source_type: raw.source_type as any,
    risk_category: raw.risk_category,
    ai_finding: raw.ai_finding,
    ai_reasoning: raw.ai_reasoning,
    evidence_slot_package: raw.evidence_slot_package ?? null,
    formula_check_results: raw.formula_check_results ?? null,
    earthwork_audit_results: raw.earthwork_audit_results ?? null,
    project_composition_consistency: raw.project_composition_consistency ?? null,
    review_status: raw.review_status ?? null,
    conclusion_type: raw.conclusion_type ?? null,
    suggested_revision: raw.suggested_revision ?? '',
    human_decision: mapDecision(raw.human_decision) as any,
    human_note: raw.human_note,
    human_edited_risk_level: raw.human_edited_risk_level as any,
    human_edited_finding: raw.human_edited_finding,
    is_false_positive: raw.is_false_positive,
    decided_by: raw.decided_by,
    decided_at: raw.decided_at,
    clause_location: {
      page_number: raw.page_number,
      paragraph_index: raw.paragraph_index,
      highlight_anchor: raw.highlight_anchor,
    },
    risk_evidence: [
      {
        id: `ev-${raw.id}`,
        evidence_text: raw.clause_text,
        context_before: '',
        context_after: '',
        page_number: raw.page_number,
        paragraph_index: raw.paragraph_index,
        char_offset_start: raw.char_offset_start,
        char_offset_end: raw.char_offset_end,
        highlight_color: raw.risk_level === 'HIGH' ? '#FFEBEE' : raw.risk_level === 'MEDIUM' ? '#FFF3E0' : '#E8F5E9',
        is_primary: true,
      },
    ],
  };
}

export interface ReviewItemListResponse {
  items: ReviewItem[];
  total: number;
  next_cursor: string | null;
}

export interface DecisionResponse {
  item_id: string;
  session_id: string;
  decision: string;
  decided_by: string;
  decided_at: string;
  message: string;
  progress?: {
    decided_high_risk: number;
    total_high_risk: number;
    all_high_risk_completed: boolean;
  };
}

export interface RevokeResponse {
  item_id: string;
  human_decision: string;
  revoked_at: string;
}

export interface BatchConfirmResponse {
  confirmed_count: number;
  failed_count: number;
  message: string;
  all_medium_risk_completed?: boolean;
}

export async function listItems(sessionId: string, params?: {
  risk_level?: string;
  human_decision?: string;
  cursor?: string;
  limit?: number;
}): Promise<ReviewItemListResponse> {
  const searchParams = new URLSearchParams();
  if (params?.risk_level) searchParams.set('risk_level', params.risk_level);
  if (params?.human_decision) searchParams.set('human_decision', params.human_decision);
  if (params?.cursor) searchParams.set('cursor', params.cursor);
  if (params?.limit) searchParams.set('limit', String(params.limit));
  const qs = searchParams.toString();
  const raw = await apiClient.get<{ items: BackendReviewItem[]; total: number; next_cursor: string | null }>(
    `/sessions/${sessionId}/items${qs ? `?${qs}` : ''}`
  );
  return {
    items: raw.items.map(transformItem),
    total: raw.total,
    next_cursor: raw.next_cursor,
  };
}

export async function getItem(sessionId: string, itemId: string): Promise<ReviewItem> {
  const raw = await apiClient.get<BackendReviewItem>(`/sessions/${sessionId}/items/${itemId}`);
  return transformItem(raw);
}

export function submitDecision(sessionId: string, itemId: string, body: {
  decision: string;
  human_note: string;
  edited_risk_level?: string | null;
  edited_finding?: string | null;
  is_false_positive?: boolean;
  client_submitted_at?: string;
}): Promise<DecisionResponse> {
  const idempotencyKey = crypto.randomUUID();
  return apiClient.post<DecisionResponse>(
    `/sessions/${sessionId}/items/${itemId}/decision`,
    body,
    { 'Idempotency-Key': idempotencyKey }
  );
}

export function revokeDecision(sessionId: string, itemId: string): Promise<RevokeResponse> {
  return apiClient.delete<RevokeResponse>(`/sessions/${sessionId}/items/${itemId}/decision`);
}

export function batchConfirm(sessionId: string, itemIds: string[], note: string): Promise<BatchConfirmResponse> {
  return apiClient.post<BatchConfirmResponse>(`/sessions/${sessionId}/items/batch-confirm`, {
    item_ids: itemIds,
    note,
  });
}
