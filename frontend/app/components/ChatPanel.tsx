"use client";

import { useState, useRef, useEffect } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type DisplayMessage = { role: "user" | "assistant"; text: string };

const SPLIT_URL_RE = /(https?:\/\/[^\s]+)/g;
const IS_URL_RE = /^https?:\/\//; // non-global: safe to reuse, no lastIndex state

// Chat replies are plain strings, so a payment link is just text unless we
// find and wrap URLs as real <a> tags ourselves.
function renderWithLinks(text: string) {
  return text.split(SPLIT_URL_RE).map((part, i) =>
    IS_URL_RE.test(part) ? (
      <a key={i} href={part} target="_blank" rel="noopener noreferrer" className="underline">
        {part}
      </a>
    ) : (
      <span key={i}>{part}</span>
    )
  );
}

export default function ChatPanel({ onActivity }: { onActivity?: () => void }) {
  // Generated client-side only, in an effect: doing this in useState's
  // initializer runs it once during SSR and again on client hydration,
  // producing two different UUIDs and a hydration mismatch.
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
    // Scroll only this panel's own message list, not scrollIntoView() on a
    // marker div — that scrolls every scrollable ancestor into view,
    // including the whole page, which was yanking the window down on send.
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
    <div className="flex h-[600px] flex-col rounded border border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-3">
        <div className="font-medium">Shopping assistant</div>
        <div className="text-xs text-slate-500">session {sessionId.slice(0, 8)}</div>
      </div>

      <div ref={messageListRef} className="flex-1 space-y-3 overflow-y-auto p-4">
        {displayMessages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
            <span
              className={
                "inline-block max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm " +
                (m.role === "user" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-900")
              }
            >
              {renderWithLinks(m.text)}
            </span>
          </div>
        ))}
        {loading && <div className="text-left text-sm text-slate-400">Thinking…</div>}
        {error && <div className="rounded bg-red-50 p-2 text-sm text-red-700">{error}</div>}
      </div>

      <div className="flex gap-2 border-t border-slate-200 p-3">
        <input
          className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
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
            "rounded bg-slate-900 px-4 py-2 text-sm text-white " +
            (loading || !input.trim() ? "pointer-events-none opacity-40" : "")
          }
        >
          Send
        </button>
      </div>
    </div>
  );
}
