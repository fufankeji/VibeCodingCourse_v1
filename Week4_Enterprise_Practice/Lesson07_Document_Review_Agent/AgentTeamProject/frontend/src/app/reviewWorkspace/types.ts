import type {
  LangExtractFactsResponse,
  ReviewDocumentContentResponse,
  ReviewPipelineStatusResponse,
  ReviewRuleTopicsResponse,
  SessionResponse,
} from '../api/sessions';
import type { ReviewItem } from '../types';

export type ReviewWorkspaceMode = 'document' | 'fields' | 'scanning' | 'review';
export type ViewerMode = 'pdf' | 'parsed';

export interface WorkspaceLoadState {
  session: boolean;
  document: boolean;
  fields: boolean;
  pipeline: boolean;
  items: boolean;
  ruleTopics: boolean;
  facts: boolean;
}

export interface WorkspaceData {
  session: SessionResponse | null;
  documentContent: ReviewDocumentContentResponse | null;
  pipelineStatus: ReviewPipelineStatusResponse | null;
  facts: LangExtractFactsResponse | null;
  items: ReviewItem[];
  ruleTopics: ReviewRuleTopicsResponse | null;
}
