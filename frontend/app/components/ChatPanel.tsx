"use client";

import { useState, useRef, useEffect } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type DisplayMessage = { role: "user" | "assistant"; text: string };

const SPLIT_URL_RE = /(https?:\/\/[^\s]+)/g;
const IS_URL_RE = /^https?:\/\//; // non-global: safe to reuse, no lastIndex state
// Prevent markdown or sentence punctuation from corrupting payment-link URLs.
const TRAILING_JUNK_RE = /[*_)\]},.:;!?'"]+$/;

// SKU IDs are useful for backend/audit correlation but are not customer-facing
// product details. Keep a UI-side safeguard in case the model includes one.
function hideInternalSku(text: string) {
  return text
    .replace(/\s*\(sku-[a-z0-9-]+\)/gi, "")
    .replace(/\bsku-[a-z0-9-]+\b/gi, "")
    .replace(/[ \t]{2,}/g, " ");
}

// Convert payment-link URLs in plain-text replies into clickable links.
function renderWithLinks(text: string) {
  return hideInternalSku(text).split(SPLIT_URL_RE).map((part, i) => {
    if (!IS_URL_RE.test(part)) return <span key={i}>{part}</span>;
    const junk = part.match(TRAILING_JUNK_RE)?.[0] ?? "";
    const url = junk ? part.slice(0, -junk.length) : part;
    return (
      <span key={i}>
        <a href={url} target="_blank" rel="noopener noreferrer" className="text-accent underline underline-offset-2">
          {url}
        </a>
        {junk}
      </span>
    );
  });
}

export default function ChatPanel({ onActivity }: { onActivity?: () => void }) {
  // Generate the session ID client-side to avoid SSR hydration mismatches.
  const [sessionId, setSessionId] = useState("");
  useEffect(() => {
    setSessionId(crypto.randomUUID());
  }, []);
  const [backendHistory, setBackendHistory] = useState<any[]>([]);
  const [displayMessages, setDisplayMessages] = useState<DisplayMessage[]>([
    { role: "assistant", text: "Hi! Tell me what you're looking for and a budget, and I'll help you check out." },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messageListRef = useRef<HTMLDivElement>(null);
  const sendingRef = useRef(false); // guards double-submit without disabling focused elements

  useEffect(() => {
    // Keep the page position fixed while scrolling the chat list.
    const el = messageListRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [displayMessages, loading]);

  async function send() {
    const text = input.trim();
    if (!text || sendingRef.current) return;
    sendingRef.current = true;

    const nextHistory = [...backendHistory, { role: "user", content: text }];
    setDisplayMessages((m) => [...m, { role: "user", text }]);
    setInput("");
    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ history: nextHistory, session_id: sessionId }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Request failed (${res.status})`);
      }
      const data = await res.json();
      setBackendHistory(data.messages);
      setDisplayMessages((m) => [...m, { role: "assistant", text: data.reply }]);
      onActivity?.();
    } catch (e: any) {
      setError(e.message || "Something went wrong talking to the agent.");
    } finally {
      setLoading(false);
      sendingRef.current = false;
    }
  }

  return (
    <div className="flex h-[600px] flex-col rounded-xl border border-border bg-card shadow-sm">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <span className="h-2 w-2 rounded-full bg-emerald-500" />
        <div>
          <div className="font-medium text-card-foreground">Shopping assistant</div>
          <div className="text-xs text-muted-foreground">session {sessionId.slice(0, 8)}</div>
        </div>
      </div>

      <div ref={messageListRef} className="flex-1 space-y-3 overflow-y-auto p-4">
        {displayMessages.map((m, i) => (
          <div key={i} className={"flex items-end gap-2 " + (m.role === "user" ? "justify-end" : "justify-start")}>
            {m.role === "assistant" && (
              <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground">
                AI
              </div>
            )}
            <span
              className={
                "inline-block max-w-[80%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm " +
                (m.role === "user"
                  ? "rounded-br-sm bg-primary text-primary-foreground"
                  : "rounded-bl-sm bg-muted text-card-foreground")
              }
            >
              {renderWithLinks(m.text)}
            </span>
          </div>
        ))}
        {loading && (
          <div className="flex items-end gap-2">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground">
              AI
            </div>
            <span className="inline-flex items-center gap-1 rounded-2xl rounded-bl-sm bg-muted px-3 py-2.5">
              <span className="typing-dot h-1.5 w-1.5 rounded-full bg-secondary" />
              <span className="typing-dot h-1.5 w-1.5 rounded-full bg-secondary" />
              <span className="typing-dot h-1.5 w-1.5 rounded-full bg-secondary" />
            </span>
          </div>
        )}
        {error && <div className="rounded-lg bg-destructive/10 p-2 text-sm text-destructive">{error}</div>}
      </div>

      <div className="flex gap-2 border-t border-border p-3">
        <input
          className="flex-1 rounded-full border border-border bg-background px-4 py-2 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-ring/30"
          placeholder="e.g. I need a running shoe under 3000 rupees"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              send();
            }
          }}
          aria-busy={loading}
        />
        <button
          onClick={send}
          aria-disabled={loading || !input.trim()}
          className={
            "rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition " +
            (loading || !input.trim() ? "pointer-events-none opacity-40" : "hover:bg-primary/90")
          }
        >
          Send
        </button>
      </div>
    </div>
  );
}
