import { ExternalLink, HelpCircle, Target, Compass } from "lucide-react";
import { ConfidenceBadge } from "./Badges";
import { REPORT_SECTIONS } from "../lib/constants";
import type { StructuredReport } from "../types";

interface ReportViewProps {
  report: StructuredReport;
}

export default function ReportView({ report }: ReportViewProps) {
  return (
    <div className="space-y-4">
      {REPORT_SECTIONS.map(({ key, label }) => {
        const section = report[key];
        if (!section) return null;
        return (
          <div key={key} className="rounded-lg border border-border bg-surface p-4">
            <div className="flex items-center justify-between mb-2">
              <h3 className="font-semibold text-sm">{label}</h3>
              <ConfidenceBadge confidence={section.confidence} />
            </div>
            <p className="text-sm text-text/90 leading-relaxed">{section.content}</p>
            {section.sources?.length > 0 && <SourceList sources={section.sources} />}
          </div>
        );
      })}

      <div className="rounded-lg border border-border bg-surface p-4">
        <div className="flex items-center gap-2 mb-2">
          <HelpCircle size={15} className="text-accent" />
          <h3 className="font-semibold text-sm">Suggested Discovery Questions</h3>
        </div>
        <ul className="space-y-1.5">
          {report.suggested_discovery_questions?.map((q, i) => (
            <li key={i} className="text-sm text-text/90 flex gap-2">
              <span className="text-muted font-mono text-xs mt-0.5">
                {String(i + 1).padStart(2, "0")}
              </span>
              {q}
            </li>
          ))}
        </ul>
      </div>

      <div className="rounded-lg border border-border bg-surface p-4">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <Target size={15} className="text-accent" />
            <h3 className="font-semibold text-sm">Suggested Outreach Strategy</h3>
          </div>
          <ConfidenceBadge confidence={report.suggested_outreach_strategy?.confidence} />
        </div>
        <p className="text-sm text-text/90 leading-relaxed">
          {report.suggested_outreach_strategy?.content}
        </p>
        {report.suggested_outreach_strategy?.sources?.length > 0 && (
          <SourceList sources={report.suggested_outreach_strategy.sources} />
        )}
      </div>

      {report.unknowns?.length > 0 && (
        <div className="rounded-lg border border-border bg-surface p-4">
          <div className="flex items-center gap-2 mb-2">
            <Compass size={15} className="text-warning" />
            <h3 className="font-semibold text-sm">Unknowns</h3>
          </div>
          <p className="text-xs text-muted mb-2">
            Areas where research was inconclusive — worth raising directly
            rather than guessing.
          </p>
          <ul className="space-y-1.5">
            {report.unknowns.map((u, i) => (
              <li key={i} className="text-sm text-text/90 flex gap-2">
                <span className="text-warning">·</span>
                {u}
              </li>
            ))}
          </ul>
        </div>
      )}

      {report.sources?.length > 0 && (
        <div className="rounded-lg border border-border bg-surface p-4">
          <h3 className="font-semibold text-sm mb-2">All Sources</h3>
          <SourceList sources={report.sources} expanded />
        </div>
      )}
    </div>
  );
}

interface SourceListProps {
  sources: string[];
  expanded?: boolean;
}

function SourceList({ sources, expanded }: SourceListProps) {
  return (
    <div
      className={`mt-3 pt-3 border-t border-border ${
        expanded ? "" : "flex flex-wrap gap-x-3 gap-y-1"
      }`}
    >
      {expanded ? (
        <ul className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
          {sources.map((url, i) => (
            <SourceLink key={i} url={url} />
          ))}
        </ul>
      ) : (
        sources.map((url, i) => <SourceLink key={i} url={url} />)
      )}
    </div>
  );
}

function SourceLink({ url }: { url: string }) {
  const isUrl = /^https?:\/\//.test(url);
  const display = isUrl ? new URL(url).hostname.replace(/^www\./, "") : url;

  if (!isUrl) {
    return <span className="text-xs text-muted font-mono">{display}</span>;
  }

  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex items-center gap-1 text-xs font-mono text-accent hover:underline truncate"
    >
      <ExternalLink size={11} className="shrink-0" />
      {display}
    </a>
  );
}