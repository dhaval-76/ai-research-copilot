import type { Confidence, SessionStatus } from "../types";
import { STATUS_STYLES, CONFIDENCE_STYLES } from "../lib/constants";

interface StatusBadgeProps {
  status: SessionStatus;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.pending;
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded border font-mono text-xs uppercase tracking-wide ${style}`}
    >
      {status === "running" && (
        <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
      )}
      {status}
    </span>
  );
}

interface ConfidenceBadgeProps {
  confidence?: Confidence;
}

export function ConfidenceBadge({ confidence }: ConfidenceBadgeProps) {
  const style = confidence
    ? CONFIDENCE_STYLES[confidence] ?? CONFIDENCE_STYLES.low
    : CONFIDENCE_STYLES.low;

  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 rounded border font-mono text-[10px] uppercase tracking-wide ${style}`}
    >
      {confidence ?? "low"} confidence
    </span>
  );
}