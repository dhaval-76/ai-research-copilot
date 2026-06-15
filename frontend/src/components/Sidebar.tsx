import { useState, type FormEvent } from "react";
import { Plus, Search, Loader2 } from "lucide-react";
import { StatusBadge } from "./Badges";
import type { CreateSessionInput, SessionSummary } from "../types";

interface SidebarProps {
  sessions: SessionSummary[];
  selectedId: string | null;
  onSelect: (sessionId: string) => void;
  onCreate: (input: CreateSessionInput) => Promise<void>;
  creating: boolean;
}

export default function Sidebar({
  sessions,
  selectedId,
  onSelect,
  onCreate,
  creating,
}: SidebarProps) {
  const [showForm, setShowForm] = useState(sessions.length === 0);
  const [companyName, setCompanyName] = useState("");
  const [website, setWebsite] = useState("");
  const [objective, setObjective] = useState("");
  const [formError, setFormError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setFormError(null);

    if (!companyName.trim() || !objective.trim()) {
      setFormError("Company name and objective are required.");
      return;
    }

    try {
      await onCreate({ companyName, website, objective });
      setCompanyName("");
      setWebsite("");
      setObjective("");
      setShowForm(false);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not create session.");
    }
  }

  return (
    <aside className="w-full md:w-80 shrink-0 border-r border-border bg-surface flex flex-col h-full">
      <div className="p-4 border-b border-border">
        <div className="flex items-center justify-between mb-1">
          <h1 className="font-semibold text-sm tracking-wide">
            Research Copilot
          </h1>
        </div>
        <p className="text-xs text-muted font-mono">zylabs.ai</p>
      </div>

      <div className="p-4 border-b border-border">
        {!showForm ? (
          <button
            onClick={() => setShowForm(true)}
            className="w-full flex items-center justify-center gap-2 rounded-md bg-accent text-bg font-medium text-sm py-2.5 hover:bg-accent/90 transition-colors"
          >
            <Plus size={16} />
            New research session
          </button>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-3">
            <div>
              <label className="block text-xs font-mono text-muted mb-1">
                Company name
              </label>
              <input
                value={companyName}
                onChange={(e) => setCompanyName(e.target.value)}
                placeholder="e.g. Stripe"
                className="w-full bg-surface2 border border-border rounded px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </div>
            <div>
              <label className="block text-xs font-mono text-muted mb-1">
                Website (optional)
              </label>
              <input
                value={website}
                onChange={(e) => setWebsite(e.target.value)}
                placeholder="https://stripe.com"
                className="w-full bg-surface2 border border-border rounded px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
              />
            </div>
            <div>
              <label className="block text-xs font-mono text-muted mb-1">
                Research objective
              </label>
              <textarea
                value={objective}
                onChange={(e) => setObjective(e.target.value)}
                placeholder="What are you preparing for? e.g. Sales call to pitch our fraud detection API"
                rows={3}
                className="w-full bg-surface2 border border-border rounded px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-accent resize-none"
              />
            </div>

            {formError && <p className="text-xs text-danger">{formError}</p>}

            <div className="flex gap-2">
              <button
                type="submit"
                disabled={creating}
                className="flex-1 flex items-center justify-center gap-2 rounded-md bg-accent text-bg font-medium text-sm py-2 hover:bg-accent/90 transition-colors disabled:opacity-60"
              >
                {creating && <Loader2 size={14} className="animate-spin" />}
                Start research
              </button>
              {sessions.length > 0 && (
                <button
                  type="button"
                  onClick={() => setShowForm(false)}
                  className="rounded-md border border-border text-sm px-3 py-2 text-muted hover:text-text transition-colors"
                >
                  Cancel
                </button>
              )}
            </div>
          </form>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        {sessions.length === 0 ? (
          <div className="p-4 text-sm text-muted flex flex-col items-center text-center mt-8 gap-2">
            <Search size={20} className="text-border" />
            No research sessions yet. Start one above.
          </div>
        ) : (
          <ul>
            {sessions.map((s) => (
              <li key={s.id}>
                <button
                  onClick={() => onSelect(s.id)}
                  className={`w-full text-left px-4 py-3 border-b border-border transition-colors ${
                    s.id === selectedId ? "bg-surface2" : "hover:bg-surface2/60"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="font-medium text-sm truncate">
                      {s.company_name}
                    </span>
                    <StatusBadge status={s.status} />
                  </div>
                  <p className="text-xs text-muted truncate">{s.objective}</p>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}