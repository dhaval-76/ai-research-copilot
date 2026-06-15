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

  // Reset local state when switching sessions
  useEffect(() => {
    setEvents([]);
    setRunning(false);
    setReport(session.report);
    setRunError(null);
    setChatMessages(null);

    if (session.report) {
      getChatHistory(session.id)
        .then((res) => setChatMessages(res.messages))
        .catch(() => setChatMessages([]));
    }
  }, [session.id]);

  function handleRun() {
    setEvents([]);
    setRunError(null);
    setRunning(true);

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

  const canRun = session.status === "pending" || session.status === "failed";

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

        {/* Run button */}
        {canRun && !running && (
          <button
            onClick={handleRun}
            className="flex items-center gap-2 rounded-md bg-accent text-bg font-medium text-sm px-4 py-2 hover:bg-accent/90 transition-colors"
          >
            <Play size={15} />
            {session.status === "failed" ? "Retry research" : "Run research"}
          </button>
        )}

        {/* Error state */}
        {(runError || session.error) && !running && (
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

        {/* Loading state (no events yet) */}
        {running && events.length === 0 && (
          <div className="flex items-center gap-2 text-sm text-muted">
            <Loader2 size={15} className="animate-spin" />
            Starting workflow…
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