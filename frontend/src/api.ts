import type {
  ChatMessage,
  CreateSessionInput,
  CreateSessionResponse,
  ProgressEvent,
  SessionDetail,
  SessionSummary,
} from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch {
      // ignore JSON parse errors on error responses
    }
    throw new ApiError(detail, res.status);
  }

  return res.json() as Promise<T>;
}

export function createSession(
  input: CreateSessionInput
): Promise<CreateSessionResponse> {
  return request("/sessions", {
    method: "POST",
    body: JSON.stringify({
      company_name: input.companyName,
      website: input.website,
      objective: input.objective,
    }),
  });
}

export function regenerateSession(sessionId: string): Promise<SessionDetail> {
  return request(`/sessions/${sessionId}/regenerate`, { method: "POST" });
}

export function listSessions(): Promise<SessionSummary[]> {
  return request("/sessions");
}

export function getSession(sessionId: string): Promise<SessionDetail> {
  return request(`/sessions/${sessionId}`);
}

export function getChatHistory(
  sessionId: string
): Promise<{ messages: ChatMessage[] }> {
  return request(`/sessions/${sessionId}/chat`);
}

export function postChatMessage(
  sessionId: string,
  message: string
): Promise<{ message: ChatMessage }> {
  return request(`/sessions/${sessionId}/chat`, {
    method: "POST",
    body: JSON.stringify({ message }),
  });
}

/**
 * Streams workflow progress via Server-Sent Events.
 *
 * Returns a function to close the connection early.
 */
export function streamRun(
  sessionId: string,
  onEvent: (event: ProgressEvent) => void,
  onError?: (err: unknown) => void
): () => void {
  const source = new EventSource(`${API_BASE}/sessions/${sessionId}/run`);

  source.onmessage = (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data) as ProgressEvent;
      onEvent(data);
      if (data.done) {
        source.close();
      }
    } catch (err) {
      onError?.(err);
      source.close();
    }
  };

  source.onerror = (err: Event) => {
    onError?.(err);
    source.close();
  };

  return () => source.close();
}