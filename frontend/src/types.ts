/**
 * Types mirroring backend/app/models/schemas.py and
 * backend/app/graph/state.py (StructuredReport, ReportSection, etc.)
 *
 * Keep these in sync with the backend schemas -- if a field is added/
 * renamed there, update it here too. This is the contract boundary
 * between frontend and backend.
 */

export type Confidence = "high" | "medium" | "low";

export type ResearchMode = "sales" | "investment" | "competitive" | "general";

export type SessionStatus = "pending" | "running" | "completed" | "failed";

export interface ReportSection {
  content: string;
  confidence: Confidence;
  sources: string[];
}

export interface StructuredReport {
  company_overview: ReportSection;
  products_and_services: ReportSection;
  target_customers: ReportSection;
  business_signals: ReportSection;
  risks_and_challenges: ReportSection;
  suggested_discovery_questions: string[];
  suggested_outreach_strategy: ReportSection;
  unknowns: string[];
  sources: string[];
}

export interface SessionSummary {
  id: string;
  company_name: string;
  website: string;
  objective: string;
  research_mode: ResearchMode | null;
  status: SessionStatus;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface SessionDetail extends SessionSummary {
  report: StructuredReport | null;
  progress_events: ProgressEvent[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  created_at?: string | null;
}

/**
 * One SSE event from GET /sessions/{id}/run
 */
export interface ProgressEvent {
  node: string;
  status: string;
  done: boolean;
  report?: StructuredReport;
  error?: string;
}

export interface CreateSessionInput {
  companyName: string;
  website: string;
  objective: string;
}

export interface CreateSessionResponse {
  session_id: string;
  status: string;
  existing: boolean;
}