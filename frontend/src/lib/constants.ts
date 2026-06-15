import type { Confidence, SessionStatus } from "../types";

export const NODE_LABELS: Record<string, string> = {
  planner: "Planning research",
  competitor_research: "Competitor research",
  research: "Researching",
  gap_fill: "Refining research",
  analyze: "Analyzing findings",
  quality_check: "Quality check",
  report_generation: "Generating report",
  error: "Error",
};

export const CONFIDENCE_STYLES: Record<Confidence, string> = {
  high: "text-accent border-accent/40 bg-accent/10",
  medium: "text-warning border-warning/40 bg-warning/10",
  low: "text-danger border-danger/40 bg-danger/10",
};

export const STATUS_STYLES: Record<SessionStatus, string> = {
  pending: "text-muted border-border bg-surface2",
  running: "text-accent border-accent/40 bg-accent/10",
  completed: "text-accent border-accent/40 bg-accent/10",
  failed: "text-danger border-danger/40 bg-danger/10",
};

export interface ReportSectionDef {
  key:
    | "company_overview"
    | "products_and_services"
    | "target_customers"
    | "business_signals"
    | "risks_and_challenges";
  label: string;
}

export const REPORT_SECTIONS: ReportSectionDef[] = [
  { key: "company_overview", label: "Company Overview" },
  { key: "products_and_services", label: "Products & Services" },
  { key: "target_customers", label: "Target Customers" },
  { key: "business_signals", label: "Business Signals" },
  { key: "risks_and_challenges", label: "Risks & Challenges" },
];