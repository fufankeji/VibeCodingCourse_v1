import { apiClient } from './client';

export interface ExecutorType {
  id: string;
  label: string;
  description: string;
  enabled: boolean;
}

export interface ExpertReviewBrief {
  item_name: string;
  review_objective: string;
  evidence_instruction: string;
  judgement_basis: string;
  pass_condition: string;
  issue_condition: string;
  regulation_text?: string;
}

export interface CheckItemPayload {
  id?: string;
  topic_id?: string;
  rule_id?: string;
  executor_type_id?: string;
  review_type?: string;
  review_sub_type?: string;
  status?: string;
  conclusion?: string;
  evidence_scope?: Record<string, unknown>;
  target_fields?: string[];
  regulation_clauses?: string[];
  review_criteria?: string;
  expected_result?: string;
  failure_conditions?: string[];
  evidence_slots?: Array<Record<string, unknown>>;
  formula_checks?: Array<Record<string, unknown>>;
  expert_brief?: ExpertReviewBrief;
  source_rule_snapshot?: Record<string, unknown>;
  enabled?: boolean;
}

export interface PreviewCheckItemPayload extends CheckItemPayload {
  session_id: string;
}

export interface EvidenceAnchor {
  page?: number;
  block_id?: string;
  bbox?: number[];
  coordinate_mode?: string;
  page_width?: number | null;
  page_height?: number | null;
}

export interface RetrievalMatch {
  chunk_id?: string;
  page?: number;
  page_end?: number;
  primary_page?: number;
  page_range?: number[];
  chunk_index?: number;
  section?: string;
  anchors?: EvidenceAnchor[];
  block_ids?: string[];
  bbox_count?: number;
  score?: number;
  vector_score?: number;
  bm25_score?: number;
  vector_rank?: number;
  bm25_rank?: number;
  neighbor_rank?: number;
  final_rank?: number;
  retrieval_sources?: string[];
  source_ranks?: Record<string, unknown>;
  rerank_score?: number;
  rerank_rank?: number;
  neighbor_of?: string;
  text?: string;
  [key: string]: unknown;
}

export interface ProjectCompositionSource extends RetrievalMatch {
  material_type?: string;
}

export interface ProjectCompositionFieldComparison {
  field?: string;
  label?: string;
  status?: 'match' | 'mismatch' | 'missing' | string;
  body_value?: number | null;
  reference_value?: number | null;
  difference?: number | null;
}

export interface ProjectCompositionConsistency {
  status?: 'match' | 'mismatch' | 'needs_review' | string;
  reason?: string;
  body_source?: ProjectCompositionSource | null;
  reference_source?: ProjectCompositionSource | null;
  field_comparisons?: ProjectCompositionFieldComparison[];
}

export interface PreviewAgentTrace {
  query?: string;
  retrieval_mode?: string;
  llm_model?: string;
  persisted?: boolean;
  artifact_dir?: string;
  chunk_count?: number;
  facts_available?: boolean;
  cross_chapter_findings_available?: boolean;
  vector_store?: string;
  [key: string]: unknown;
}

export interface EvidenceSlotPackage {
  source?: string;
  slot_count?: number;
  required_slot_count?: number;
  matched_required_slot_count?: number;
  missing_required_slot_ids?: string[];
  truncated?: boolean;
  slot_limit?: number;
  truncated_required_slot_ids?: string[];
  slots?: Array<Record<string, unknown>>;
}

export interface FormulaCheckResults {
  source?: string;
  check_count?: number;
  pass_count?: number;
  fail_count?: number;
  missing_count?: number;
  unsupported_count?: number;
  checks?: Array<Record<string, unknown>>;
}

export interface PreviewCheckItemResponse {
  check_item: CheckItemSpec;
  evidence_bundle: {
    evidence_texts?: string[];
    evidence_locations?: Array<Record<string, unknown>>;
    retrieval_matches?: RetrievalMatch[];
    matched_target_fields?: string[];
    missing_target_fields?: string[];
    structured_facts?: unknown[];
    cross_reference_findings?: unknown[];
    project_composition_consistency?: ProjectCompositionConsistency;
    evidence_slot_package?: EvidenceSlotPackage;
    formula_check_results?: FormulaCheckResults;
    langextract_grounding?: unknown[] | Record<string, unknown>;
    regulation_context?: Array<Record<string, unknown>>;
    retrieval_score?: number;
    source?: string;
    [key: string]: unknown;
  };
  precheck_result: {
    executor_type_id?: string;
    handler_id?: string;
    execution_status?: string;
    checks?: Array<Record<string, unknown>>;
    evidence_scope?: Record<string, string[]>;
    target_fields?: string[];
    regulation_clauses?: string[];
    llm_required?: boolean;
    next_action?: string;
    summary?: string;
    [key: string]: unknown;
  };
  review_conclusion: {
    status?: string;
    summary?: string;
    actual_value?: string;
    expected_value?: string;
    fix_suggestion?: string;
    confidence?: number;
    next_action?: string;
    llm_required?: boolean;
    [key: string]: unknown;
  };
  suggested_rule_improvements: string[];
  agent_trace?: PreviewAgentTrace;
}

export interface CheckItemSpec {
  id: string;
  topic_id: string;
  rule_id: string;
  executor_type_id: string;
  review_type: string;
  review_sub_type: string;
  status: string;
  conclusion: string;
  evidence_scope: Record<string, unknown>;
  target_fields: string[];
  regulation_clauses: string[];
  review_criteria: string;
  expected_result: string;
  failure_conditions: string[];
  evidence_slots: Array<Record<string, unknown>>;
  formula_checks: Array<Record<string, unknown>>;
  source_rule_snapshot: Record<string, unknown>;
  enabled: boolean;
}

export function listExecutorTypes(): Promise<{ items: ExecutorType[] }> {
  return apiClient.get<{ items: ExecutorType[] }>('/review-config/executor-types');
}

export function createCheckItem(body: CheckItemPayload): Promise<CheckItemSpec> {
  return apiClient.post<CheckItemSpec>('/review-config/check-items', body);
}

export function previewCheckItem(body: PreviewCheckItemPayload): Promise<PreviewCheckItemResponse> {
  return apiClient.post<PreviewCheckItemResponse>('/review-config/check-items/preview', body);
}

export function updateCheckItem(itemId: string, body: CheckItemPayload): Promise<CheckItemSpec> {
  return apiClient.patch<CheckItemSpec>(`/review-config/check-items/${itemId}`, body);
}

export function deleteCheckItem(itemId: string): Promise<{ id: string; deleted: boolean }> {
  return apiClient.delete<{ id: string; deleted: boolean }>(`/review-config/check-items/${itemId}`);
}
