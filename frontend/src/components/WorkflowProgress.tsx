import { CheckCircle2, Loader2, AlertCircle, RotateCcw } from "lucide-react";
import { NODE_LABELS } from "../lib/constants";
import type { ProgressEvent } from "../types";

interface WorkflowProgressProps {
  events: ProgressEvent[];
  running: boolean;
}

/**
 * Renders the live workflow trace as a log, not a fixed step list --
 * the graph has conditional loops (gap_fill -> research can repeat),
 * so a linear progress bar would misrepresent what's happening.
 */
export default function WorkflowProgress({ events, running }: WorkflowProgressProps) {
  if (events.length === 0 && !running) return null;

  return (
    <div className="rounded-lg border border-border bg-surface p-4">
      <h3 className="text-xs font-mono uppercase tracking-wide text-muted mb-3">
        Workflow trace
      </h3>
      <ul className="space-y-2">
        {events.map((e, i) => (
          <li key={i} className="flex items-start gap-2.5 text-sm">
            <span className="mt-0.5">
              {e.node === "error" ? (
                <AlertCircle size={15} className="text-danger" />
              ) : e.node === "gap_fill" ? (
                <RotateCcw size={15} className="text-warning" />
              ) : (
                <CheckCircle2 size={15} className="text-accent" />
              )}
            </span>
            <div>
              <span className="font-mono text-xs text-muted mr-2">
                {NODE_LABELS[e.node] || e.node}
              </span>
              <span className={e.node === "error" ? "text-danger" : "text-text"}>
                {e.status}
              </span>
            </div>
          </li>
        ))}
        {running && (
          <li className="flex items-center gap-2.5 text-sm text-muted">
            <Loader2 size={15} className="animate-spin" />
            <span className="font-mono text-xs">Working…</span>
          </li>
        )}
      </ul>
    </div>
  );
}