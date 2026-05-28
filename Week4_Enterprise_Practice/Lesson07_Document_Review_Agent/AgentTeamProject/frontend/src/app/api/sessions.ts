import { apiClient } from './client';
import type { EvidenceSlotPackage, RetrievalMatch } from './reviewConfig';

export interface ProgressSummary {
  total_high_risk: number;
  decided_high_risk: number;
  total_medium_risk: number;
  total_low_risk: number;
  pending_high_risk: number;
  completion_percent: number;
}

export interface SessionResponse {
  id: string;
  contract_id: string;
  state: string;
  hitl_subtype: string | null;
  is_scanned_document: boolean;
  created_by: string;
  created_at: string;
  completed_at: string | null;
  updated_at: string;
  progress_summary: ProgressSummary;
}

export interface SessionRecoveryResponse {
  session_id: string;
  state: string;
  last_updated: string;
  pending_high_risk_count: number;
  resumable: boolean;
  message: string;
}

export interface ReviewDocumentBlock {
  block_id: string;
  page: number;
  type: string;
  text: string;
  html?: string;
  image_path?: string;
  bbox: number[];
  section_hint: string;
}

export interface ReviewDocumentPage {
  page_number: number;
  blocks: ReviewDocumentBlock[];
}

export interface ReviewDocumentOutlineItem {
  id: string;
  title: string;
  page_number: number;
  level: number;
}

export interface ReviewDocumentContentResponse {
  session_id: string;
  contract_id: string;
  title: string;
  file_type: string;
  source: string;
  page_count: number;
  outline: ReviewDocumentOutlineItem[];
  pages: ReviewDocumentPage[];
}

export interface ReviewLogicType {
  type: string;
  label: string;
}

export interface ReviewCheckItem {
  id: string;
  topic_id: string;
  source_issue_id?: string;
  rule_id?: string;
  rule_name?: string;
  executor_type_id?: string;
  review_type: string;
  review_sub_type: string;
  review_logic: ReviewLogicType[];
  review_logic_types: string[];
  status: string;
  conclusion: string;
  evidence_texts: string[];
  evidence_locations: Array<{
    page_number?: number | null;
    paragraph_index?: number | null;
    highlight_anchor?: string;
    char_offset_start?: number | null;
    char_offset_end?: number | null;
  }>;
  regulation_clauses: string[];
  reasoning_process: Record<string, unknown>;
  ai_or_human_source: string;
  human_review_status: string;
  evidence_scope?: {
    chapters?: string[];
    tables?: string[];
    attachments?: string[];
    regulations?: string[];
    [key: string]: unknown;
  };
  target_fields?: string[];
  review_criteria?: string;
  expected_result?: string;
  failure_conditions?: string[];
  evidence_slots?: Array<Record<string, unknown>>;
  formula_checks?: Array<Record<string, unknown>>;
  source_rule_snapshot?: Record<string, unknown>;
  enabled?: boolean;
  risk_level?: string;
  confidence_score?: number | null;
}

export interface ReviewRuleSummary extends ReviewCheckItem {
  rule_id: string;
  rule_name: string;
  review_item_name?: string;
}

export interface ReviewRuleItem {
  item_id: string;
  item_name: string;
  logic_types: string[];
  rules: ReviewRuleSummary[];
}

export interface ReviewRuleTopic {
  id: string;
  name: string;
  sequence: number;
  check_status: string;
  check_item_count: number;
  configured_check_item_count: number;
  error_item_count: number;
  detected_error_item_count: number;
  reference_error_count: number;
  main_review_types: string[];
  check_items: ReviewCheckItem[];
  rule_candidates?: ReviewRuleSummary[];
  topic_id: string;
  topic_name: string;
  topic_category: string;
  description: string;
  items: ReviewRuleItem[];
}

export interface ReviewRuleTopicsResponse {
  session_id: string;
  source: 'artifact' | 'rule_set' | 'session_items';
  topics: ReviewRuleTopic[];
}

export interface RetrievalDebugResponse {
  status: 'ready' | 'degraded' | 'unavailable';
  query: string;
  reason?: string;
  matches: RetrievalMatch[];
  evidence_slot_package?: EvidenceSlotPackage;
  trace: {
    persisted?: boolean;
    artifact_dir?: string;
    chunk_count?: number;
    vector_store?: string;
    vector_available?: boolean;
    bm25_available?: boolean;
    rerank_available?: boolean;
    retrieval_mode?: string;
    top_k?: number;
    requested_top_k?: number;
    top_k_clamped?: boolean;
    requested_use_vector?: boolean;
    requested_use_bm25?: boolean;
    requested_use_neighbors?: boolean;
    requested_use_rerank?: boolean;
    [key: string]: unknown;
  };
}

export function getSession(sessionId: string): Promise<SessionResponse> {
  return apiClient.get<SessionResponse>(`/sessions/${sessionId}`);
}

export function getSessionRecovery(sessionId: string): Promise<SessionRecoveryResponse> {
  return apiClient.get<SessionRecoveryResponse>(`/sessions/${sessionId}/recovery`);
}

export function getReviewDocumentContent(sessionId: string): Promise<ReviewDocumentContentResponse> {
  return apiClient.get<ReviewDocumentContentResponse>(`/sessions/${sessionId}/document-content`);
}

export function getReviewRuleTopics(sessionId: string): Promise<ReviewRuleTopicsResponse> {
  return apiClient.get<ReviewRuleTopicsResponse>(`/sessions/${sessionId}/rule-topics`);
}

export function runRetrievalDebug(
  sessionId: string,
  body: {
    query?: string;
    evidence_slot?: Record<string, unknown>;
    top_k?: number;
    use_vector?: boolean;
    use_bm25?: boolean;
    use_neighbors?: boolean;
    use_rerank?: boolean;
  }
): Promise<RetrievalDebugResponse> {
  return apiClient.post<RetrievalDebugResponse>(`/sessions/${sessionId}/retrieval-debug`, body);
}

export function retryParse(sessionId: string) {
  return apiClient.post<{ session_id: string; state: string; message: string }>(`/sessions/${sessionId}/retry-parse`);
}

export function abortSession(sessionId: string, reason?: string) {
  return apiClient.post<{ session_id: string; state: string; message: string }>(
    `/sessions/${sessionId}/abort`,
    reason ? { reason } : undefined
  );
}
