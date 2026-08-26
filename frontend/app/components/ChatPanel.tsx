"use client";

import { useState, useRef, useEffect } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type DisplayMessage = { role: "user" | "assistant"; text: string };

export default function ChatPanel({ onActivity }: { onActivity?: () => void }) {
  const [sessionId] = useState(() => crypto.randomUUID());
  const [backendHistory, setBackendHistory] = useState<any[]>([]);
  const [displayMessages, setDisplayMessages] = useState<DisplayMessage[]>([
    { role: "assistant", text: "Hi! Tell me what you're looking for and a budget, and I'll help you check out." },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [displayMessages, loading]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;

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
    }
  }

  return (
    <div className="flex h-[600px] flex-col rounded border border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-3">
        <div className="font-medium">Shopping assistant</div>
        <div className="text-xs text-slate-500">session {sessionId.slice(0, 8)}</div>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto p-4">
        {displayMessages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
            <span
              className={
                "inline-block max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm " +
                (m.role === "user" ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-900")
              }
            >
              {m.text}
            </span>
          </div>
        ))}
        {loading && <div className="text-left text-sm text-slate-400">Thinking…</div>}
        {error && <div className="rounded bg-red-50 p-2 text-sm text-red-700">{error}</div>}
        <div ref={bottomRef} />
      </div>

      <div className="flex gap-2 border-t border-slate-200 p-3">
        <input
          className="flex-1 rounded border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
          placeholder="e.g. I need a running shoe under 3000 rupees"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
          disabled={loading}
        />
        <button
          onClick={send}
          disabled={loading || !input.trim()}
          className="rounded bg-slate-900 px-4 py-2 text-sm text-white disabled:opacity-40"
        >
          Send
        </button>
      </div>
    </div>
  );
}
