import { useEffect, useState } from "react";
import { Play, Loader2, RefreshCw, ArrowLeft } from "lucide-react";
import { StatusBadge } from "./Badges";
import WorkflowProgress from "./WorkflowProgress";
import ReportView from "./ReportView";
import ChatPanel from "./ChatPanel";
import { streamRun, getChatHistory } from "../api";
import type { ChatMessage, ProgressEvent, SessionDetail as SessionDetailType, SessionStatus, StructuredReport } from "../types";

interface SessionDetailProps {
  session: SessionDetailType;
  onStatusChange: (sessionId: string, status: SessionStatus) => void;
  onBack: () => void;
}

export default function SessionDetail({ session, onStatusChange, onBack }: SessionDetailProps) {
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<StructuredReport | null>(session.report);
  const [runError, setRunError] = useState<string | null>(null);
  const [chatMessages, setChatMessages] = useState<ChatMessage[] | null>(null);

  // Reset local state when switching sessions; restore persisted workflow trace
  useEffect(() => {
    setEvents(session.progress_events ?? []);
    setRunning(false);
    setReport(session.report);
    setRunError(null);
    setChatMessages(null);

    if (session.report) {
      getChatHistory(session.id)
        .then((res) => setChatMessages(res.messages))
        .catch(() => setChatMessages([]));
    }
  }, [session.id, session.progress_events, session.report]);

  const isFailed = session.status === "failed";
  const isInterrupted = session.status === "running";
  const hasRunError = Boolean(runError);
  const hasPersistedError = Boolean(session.error);

  const showFailedPanel =
    !running && isFailed && (hasRunError || hasPersistedError);
  const showConnectionLostPanel = !running && isInterrupted && hasRunError;
  const showInterruptedPanel = !running && isInterrupted && !hasRunError;
  const showPrimaryButton =
    !running &&
    !showFailedPanel &&
    !showConnectionLostPanel &&
    (session.status === "pending" || isInterrupted);

  function handleRun() {
    const isFreshRun = session.status === "pending" || session.status === "failed";
    if (isFreshRun) {
      setEvents([]);
    }
    setRunError(null);
    setRunning(true);
    onStatusChange(session.id, "running");

    streamRun(
      session.id,
      (event) => {
        setEvents((prev) => [...prev, event]);

        if (event.done) {
          setRunning(false);
          if (event.error) {
            setRunError(event.error);
            onStatusChange(session.id, "failed");
          } else if (event.report) {
            setReport(event.report);
            setChatMessages([]);
            onStatusChange(session.id, "completed");
          }
        }
      },
      () => {
        setRunning(false);
        setRunError("Connection to the workflow stream was lost.");
      }
    );
  }

  const primaryButtonLabel = isInterrupted ? "Resume research" : "Run research";

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto px-6 py-6 space-y-5">
        <button
          onClick={onBack}
          className="md:hidden flex items-center gap-1.5 text-xs font-mono text-muted hover:text-text"
        >
          <ArrowLeft size={14} />
          Back to sessions
        </button>

        {/* Header */}
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h2 className="text-xl font-semibold">{session.company_name}</h2>
            <StatusBadge status={running ? "running" : session.status} />
          </div>
          {session.website && (
            <a
              href={session.website}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs font-mono text-accent hover:underline"
            >
              {session.website}
            </a>
          )}
          <p className="text-sm text-muted mt-2">{session.objective}</p>
          {session.research_mode && (
            <span className="inline-block mt-2 text-[10px] font-mono uppercase tracking-wide text-muted border border-border rounded px-2 py-0.5">
              mode: {session.research_mode}
            </span>
          )}
        </div>

        {/* Interrupted run — offer resume without treating it as a failure */}
        {showInterruptedPanel && (
          <div className="rounded-lg border border-accent/40 bg-accent/10 p-4 text-sm">
            <p className="font-medium mb-1">Research in progress</p>
            <p className="text-muted">
              This session was interrupted (e.g. a reconnect or server restart).
              Resume to continue from the last saved checkpoint.
            </p>
          </div>
        )}

        {/* Stream dropped while status is still running */}
        {showConnectionLostPanel && (
          <div className="rounded-lg border border-accent/40 bg-accent/10 p-4 text-sm">
            <p className="font-medium mb-1">Connection lost</p>
            <p className="text-muted">{runError}</p>
            <button
              onClick={handleRun}
              className="mt-3 flex items-center gap-1.5 text-xs font-mono uppercase tracking-wide border border-accent/40 rounded px-2 py-1 hover:bg-accent/10 transition-colors text-accent"
            >
              <RefreshCw size={12} />
              Resume research
            </button>
          </div>
        )}

        {/* Run / resume button */}
        {showPrimaryButton && (
          <button
            onClick={handleRun}
            className="flex items-center gap-2 rounded-md bg-accent text-bg font-medium text-sm px-4 py-2 hover:bg-accent/90 transition-colors"
          >
            {isInterrupted ? <RefreshCw size={15} /> : <Play size={15} />}
            {primaryButtonLabel}
          </button>
        )}

        {/* Workflow error — only for failed sessions */}
        {showFailedPanel && (
          <div className="rounded-lg border border-danger/40 bg-danger/10 p-4 text-sm text-danger">
            <p className="font-medium mb-1">Workflow failed</p>
            <p className="text-danger/90">{runError || session.error}</p>
            <button
              onClick={handleRun}
              className="mt-3 flex items-center gap-1.5 text-xs font-mono uppercase tracking-wide border border-danger/40 rounded px-2 py-1 hover:bg-danger/10 transition-colors"
            >
              <RefreshCw size={12} />
              Retry
            </button>
          </div>
        )}

        {/* Loading state — only before the first event of a fresh run */}
        {running && events.length === 0 && (
          <div className="flex items-center gap-2 text-sm text-muted">
            <Loader2 size={15} className="animate-spin" />
            {isInterrupted ? "Resuming workflow…" : "Starting workflow…"}
          </div>
        )}

        {/* Workflow progress trace */}
        <WorkflowProgress events={events} running={running} />

        {/* Report */}
        {report && <ReportView report={report} />}

        {/* Chat */}
        {report && chatMessages !== null && (
          <ChatPanel sessionId={session.id} initialMessages={chatMessages} />
        )}
      </div>
    </div>
  );
}