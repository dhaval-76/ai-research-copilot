import { useEffect, useRef, useState, type FormEvent } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { Send, Loader2, MessageSquare } from "lucide-react";
import { postChatMessage } from "../api";
import type { ChatMessage } from "../types";

interface ChatPanelProps {
  sessionId: string;
  initialMessages: ChatMessage[];
}

export default function ChatPanel({ sessionId, initialMessages }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMessages(initialMessages);
  }, [sessionId, initialMessages]);

  useEffect(() => {
    scrollRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const text = input.trim();
    if (!text || sending) return;

    setError(null);
    setMessages((m) => [...m, { role: "user", content: text }]);
    setInput("");
    setSending(true);

    try {
      const res = await postChatMessage(sessionId, text);
      setMessages((m) => [...m, res.message]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send message. Try again.");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="rounded-lg border border-border bg-surface flex flex-col h-[420px]">
      <div className="px-4 py-3 border-b border-border flex items-center gap-2">
        <MessageSquare size={15} className="text-accent" />
        <h3 className="font-semibold text-sm">Ask about this report</h3>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
        {messages.length === 0 && (
          <p className="text-sm text-muted">
            Ask a follow-up — e.g. "What's their biggest risk?" or "Who are
            the key decision makers?". Answers are grounded in the report
            above.
          </p>
        )}
        {messages.map((m, i) => (
          <div
            key={i}
            className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[85%] rounded-md px-3 py-2 text-sm leading-relaxed ${
                m.role === "user"
                  ? "bg-accent/15 text-text border border-accent/30"
                  : "bg-surface2 text-text/90 border border-border"
              }`}
            >
              <div className="prose prose-sm max-w-none dark:prose-invert">
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    code(props) {
                      const { children, className } = props;
                      const match = /language-(\w+)/.exec(className || "");
                    
                      return match ? (
                        <SyntaxHighlighter language={match[1]}>
                          {String(children).replace(/\n$/, "")}
                        </SyntaxHighlighter>
                      ) : (
                        <code className={className}>
                          {children}
                        </code>
                      );
                    },
                  }}
                >
                  {m.content}
                </ReactMarkdown>
              </div>
            </div>
          </div>
        ))}
        {sending && (
          <div className="flex justify-start">
            <div className="rounded-md px-3 py-2 text-sm bg-surface2 border border-border text-muted flex items-center gap-2">
              <Loader2 size={14} className="animate-spin" />
              Thinking…
            </div>
          </div>
        )}
        <div ref={scrollRef} />
      </div>

      {error && <p className="px-4 pb-1 text-xs text-danger">{error}</p>}

      <form onSubmit={handleSend} className="p-3 border-t border-border flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask a question about this report…"
          className="flex-1 bg-surface2 border border-border rounded px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-accent"
        />
        <button
          type="submit"
          disabled={sending || !input.trim()}
          className="rounded-md bg-accent text-bg px-3 py-2 disabled:opacity-50 hover:bg-accent/90 transition-colors"
        >
          <Send size={16} />
        </button>
      </form>
    </div>
  );
}