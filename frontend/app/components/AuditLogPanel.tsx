"use client";

import { useEffect, useState, useCallback } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type AuditRow = {
  id: number;
  timestamp: number;
  session_id: string | null;
  source: string;
  tool: string;
  input: string;
  amount_inr: number | null;
  bound_limit_inr: number | null;
  within_bound: number;
  result: string;
  outcome: string;
};

const OUTCOME_STYLE: Record<string, string> = {
  created: "bg-emerald-50 text-emerald-700 border-emerald-200",
  blocked_over_limit: "bg-amber-50 text-amber-800 border-amber-300",
  info: "bg-slate-50 text-slate-600 border-slate-200",
  error: "bg-red-50 text-red-700 border-red-200",
};

const SOURCE_STYLE: Record<string, string> = {
  "human-chat": "bg-indigo-50 text-indigo-700",
  "agent-to-agent": "bg-purple-50 text-purple-700",
};

export default function AuditLogPanel({ refreshSignal }: { refreshSignal?: number }) {
  const [rows, setRows] = useState<AuditRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchLog = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/audit-log?limit=25`, { cache: "no-store" });
      if (!res.ok) return;
      setRows(await res.json());
      setError(null);
    } catch {
      setError("Can't reach the backend's audit log yet.");
    }
  }, []);

  useEffect(() => {
    fetchLog();
    const id = setInterval(fetchLog, 2500); // live-updates: picks up buyer_agent.py actions too
    return () => clearInterval(id);
  }, [fetchLog]);

  useEffect(() => {
    if (refreshSignal !== undefined) fetchLog();
  }, [refreshSignal, fetchLog]);

  return (
    <div className="flex h-[600px] flex-col rounded border border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-3">
        <div className="font-medium">Agent audit log</div>
        <div className="text-xs text-slate-500">
          every tool call, bounded &amp; gated — refreshes automatically
        </div>
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {error && <div className="rounded bg-amber-50 p-2 text-xs text-amber-800">{error}</div>}
        {rows.length === 0 && !error && (
          <div className="p-2 text-xs text-slate-400">No agent actions yet — send a chat message.</div>
        )}
        {rows.map((r) => (
          <div key={r.id} className="rounded border border-slate-200 p-2 text-xs">
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="font-mono font-medium">{r.tool}</span>
              <span className={`rounded px-1.5 py-0.5 ${SOURCE_STYLE[r.source] || "bg-slate-50 text-slate-600"}`}>
                {r.source}
              </span>
            </div>
            <div className={`mb-1 inline-block rounded border px-1.5 py-0.5 ${OUTCOME_STYLE[r.outcome] || ""}`}>
              {r.outcome}
              {r.amount_inr != null && ` · ₹${r.amount_inr}`}
              {r.bound_limit_inr != null && ` / cap ₹${r.bound_limit_inr}`}
            </div>
            <div className="truncate text-slate-500">{r.input}</div>
            <div className="mt-1 text-[10px] text-slate-400">
              {new Date(r.timestamp * 1000).toLocaleTimeString()}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
