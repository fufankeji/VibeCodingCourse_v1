export type UserRole = 'reviewer' | 'submitter' | 'admin';
export type SessionState = 'parsing' | 'scanning' | 'hitl_pending' | 'completed' | 'report_ready' | 'aborted';
export type HitlSubtype = 'interrupt' | 'batch_review' | null;
export type RiskLevel = 'HIGH' | 'MEDIUM' | 'LOW';
export type SourceType = 'rule_engine' | 'ai_inference' | 'hybrid';
export type VerificationStatus = 'unverified' | 'confirmed' | 'modified' | 'skipped';
export type HumanDecision = 'pending' | 'approve' | 'edit' | 'reject';

export interface User {
  id: string;
  name: string;
  role: UserRole;
  email: string;
}

export interface ReviewSession {
  id: string;
  contract_id: string;
  state: SessionState;
  hitl_subtype: HitlSubtype;
  is_scanned_document: boolean;
  created_at: string;
  completed_at: string | null;
  progress_summary: {
    total_high_risk: number;
    decided_high_risk: number;
    total_medium_risk: number;
    total_low_risk: number;
  };
}

export interface Contract {
  id: string;
  title: string;
  original_filename: string;
  contract_status: string;
  uploaded_at: string;
  uploaded_by: string;
  session: {
    id: string;
    state: SessionState;
    hitl_subtype: HitlSubtype;
    completed_at: string | null;
    progress?: {
      decided_high_risk: number;
      total_high_risk_count: number;
    };
  };
}

export interface ExtractedField {
  id: string;
  field_name: string;
  field_label: string;
  field_value: string;
  original_value: string;
  confidence_score: number;
  needs_human_verification: boolean;
  verification_status: VerificationStatus;
  source_evidence_text: string;
  source_page_number: number;
  source_char_offset_start: number;
  source_char_offset_end: number;
}

export interface RiskEvidence {
  id: string;
  evidence_text: string;
  context_before: string;
  context_after: string;
  page_number: number;
  paragraph_index: number;
  char_offset_start: number;
  char_offset_end: number;
  highlight_color: string;
  is_primary: boolean;
}

export interface ReviewResult {
  issue_id?: string;
  review_topic?: string;
  review_item?: string;
  rule_id?: string;
  rule_name?: string;
  risk_level?: RiskLevel | string;
  issue_desc?: string;
  evidence_text?: string;
  evidence_nodes?: Array<Record<string, unknown>>;
  source_pages?: number[];
  source_bbox_list?: Array<Record<string, unknown>>;
  reasoning_summary?: string;
  fix_suggestion?: string;
  confidence?: number;
  review_status?: string;
  [key: string]: unknown;
}

export interface DecisionHistory {
  id: string;
  decision_type: HumanDecision;
  operator_id: string;
  operator_name: string;
  operated_at: string;
  human_note: string;
  original_ai_finding: string;
  original_risk_level: RiskLevel;
  edited_ai_finding: string | null;
  edited_risk_level: RiskLevel | null;
  is_false_positive: boolean;
  is_revoked: boolean;
  revoked_at: string | null;
}

export interface ReviewItem {
  id: string;
  session_id: string;
  risk_level: RiskLevel;
  confidence_score: number;
  source_type: SourceType;
  risk_category: string;
  ai_finding: string;
  ai_reasoning: string;
  evidence_slot_package?: Record<string, unknown> | null;
  formula_check_results?: Record<string, unknown> | null;
  earthwork_audit_results?: Record<string, unknown> | null;
  project_composition_consistency?: Record<string, unknown> | null;
  review_result?: ReviewResult | null;
  review_status?: string | null;
  conclusion_type?: string | null;
  suggested_revision: string;
  human_decision: HumanDecision;
  human_note: string | null;
  human_edited_risk_level: RiskLevel | null;
  human_edited_finding: string | null;
  is_false_positive: boolean;
  decided_by: string | null;
  decided_at: string | null;
  clause_location: {
    page_number: number;
    paragraph_index: number;
    highlight_anchor: string;
  };
  risk_evidence: RiskEvidence[];
  decision_history?: DecisionHistory[];
}

export interface ReportData {
  id: string;
  session_id: string;
  report_status: 'generating' | 'ready';
  generated_at: string;
  summary: {
    project_name?: string;
    construction_unit?: string;
    project_location?: string;
    construction_nature?: string;
    investment_estimate?: string;
    contract_parties: string[];
    contract_amount: string;
    effective_date: string;
    overall_risk_level: string;
    conclusion: string;
  };
  item_stats: {
    total: number;
    approved: number;
    edited: number;
    rejected: number;
    auto_passed: number;
  };
  coverage_statement: {
    covered_clause_types: string[];
    not_covered_clause_types: string[];
  };
  disclaimer: string;
}
