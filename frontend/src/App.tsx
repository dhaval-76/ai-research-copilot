import { useEffect, useState } from "react";
import { Sparkles, AlertCircle, Loader2 } from "lucide-react";
import Sidebar from "./components/Sidebar";
import SessionDetail from "./components/SessionDetail";
import { createSession, getSession, listSessions, ApiError } from "./api";
import type { CreateSessionInput, SessionDetail as SessionDetailType, SessionStatus, SessionSummary } from "./types";

type MobileView = "sidebar" | "detail";

export default function App() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedSession, setSelectedSession] = useState<SessionDetailType | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [mobileView, setMobileView] = useState<MobileView>("sidebar");

  useEffect(() => {
    refreshSessions();
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setSelectedSession(null);
      return;
    }
    getSession(selectedId)
      .then(setSelectedSession)
      .catch((err) => setLoadError(err instanceof Error ? err.message : "Could not load session."));
  }, [selectedId]);

  async function refreshSessions() {
    setLoading(true);
    try {
      const data = await listSessions();
      setSessions(data);
      if (data.length > 0 && !selectedId) {
        setSelectedId(data[0].id);
      }
      setLoadError(null);
    } catch (err) {
      if (err instanceof ApiError) {
        setLoadError(
          `Could not reach the backend (${err.message}). Is it running on the configured API URL?`
        );
      } else {
        setLoadError("Could not load sessions.");
      }
    } finally {
      setLoading(false);
    }
  }

  function handleSelect(sessionId: string) {
    setSelectedId(sessionId);
    setMobileView("detail");
  }

  async function handleCreate({ companyName, website, objective }: CreateSessionInput) {
    setCreating(true);
    try {
      const res = await createSession({ companyName, website, objective });
      await refreshSessionsAndSelect(res.session_id);
      setMobileView("detail");
    } finally {
      setCreating(false);
    }
  }

  async function refreshSessionsAndSelect(sessionId: string) {
    const data = await listSessions();
    setSessions(data);
    setSelectedId(sessionId);
  }

  function handleStatusChange(sessionId: string, status: SessionStatus) {
    setSessions((prev) =>
      prev.map((s) => (s.id === sessionId ? { ...s, status } : s))
    );
    setSelectedSession((prev) =>
      prev && prev.id === sessionId ? { ...prev, status } : prev
    );
  }

  if (loadError) {
    return (
      <div className="h-screen flex items-center justify-center bg-bg">
        <div className="max-w-md text-center px-6">
          <AlertCircle size={28} className="text-danger mx-auto mb-3" />
          <h2 className="font-semibold mb-1">Couldn't connect</h2>
          <p className="text-sm text-muted">{loadError}</p>
          <button
            onClick={refreshSessions}
            className="mt-4 text-sm font-mono text-accent hover:underline"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex">
      <div className={`${mobileView === "sidebar" ? "flex" : "hidden"} md:flex w-full md:w-auto`}>
        <Sidebar
          sessions={sessions}
          selectedId={selectedId}
          onSelect={handleSelect}
          onCreate={handleCreate}
          creating={creating}
        />
      </div>

      <div className={`${mobileView === "detail" ? "flex" : "hidden"} md:flex flex-1 min-w-0`}>
        {loading ? (
          <div className="flex-1 flex items-center justify-center text-muted gap-2 text-sm">
            <Loader2 size={16} className="animate-spin" />
            Loading…
          </div>
        ) : selectedSession ? (
          <SessionDetail
            key={selectedSession.id}
            session={selectedSession}
            onStatusChange={handleStatusChange}
            onBack={() => setMobileView("sidebar")}
          />
        ) : (
          <EmptyState />
        )}
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="flex-1 flex items-center justify-center">
      <div className="text-center max-w-sm">
        <Sparkles size={28} className="text-accent mx-auto mb-3" />
        <h2 className="font-semibold mb-1">Start a research session</h2>
        <p className="text-sm text-muted">
          Give the copilot a company, website, and what you're preparing
          for — it'll build a structured briefing you can chat with.
        </p>
      </div>
    </div>
  );
}