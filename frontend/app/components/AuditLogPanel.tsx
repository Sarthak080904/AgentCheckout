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
  order_id: string | null;
  sku_id: string | null;
  reason: string | null;
};

const OUTCOME_STYLE: Record<string, string> = {
  created: "bg-emerald-50 text-emerald-700 border-emerald-200",
  original_payment_completed: "bg-emerald-50 text-emerald-700 border-emerald-200",
  upsell_payment_created: "bg-emerald-50 text-emerald-700 border-emerald-200",
  purchase_confirmed: "bg-emerald-50 text-emerald-700 border-emerald-200",
  quote_created: "bg-emerald-50 text-emerald-700 border-emerald-200",
  upsell_offered: "bg-sky-50 text-sky-700 border-sky-200",
  purchase_confirmation_requested: "bg-sky-50 text-sky-700 border-sky-200",
  upsell_declined: "bg-slate-50 text-slate-600 border-slate-200",
  purchase_rejected: "bg-slate-50 text-slate-600 border-slate-200",
  blocked_over_limit: "bg-amber-50 text-amber-800 border-amber-300",
  duplicate_webhook_ignored: "bg-amber-50 text-amber-800 border-amber-300",
  quote_expired: "bg-amber-50 text-amber-800 border-amber-300",
  quote_reused: "bg-amber-50 text-amber-800 border-amber-300",
  info: "bg-slate-50 text-slate-600 border-slate-200",
  error: "bg-red-50 text-red-700 border-red-200",
  invalid_webhook: "bg-red-50 text-red-700 border-red-200",
  original_payment_failed: "bg-red-50 text-red-700 border-red-200",
  quote_missing: "bg-red-50 text-red-700 border-red-200",
  quote_invalid: "bg-red-50 text-red-700 border-red-200",
  quote_mismatch: "bg-red-50 text-red-700 border-red-200",
};

const SOURCE_STYLE: Record<string, string> = {
  "human-chat": "bg-primary/10 text-primary",
  "agent-to-agent": "bg-accent/10 text-accent",
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
    <div className="flex h-[600px] flex-col rounded-xl border border-border bg-card shadow-sm">
      <div className="flex items-center gap-2 border-b border-border px-4 py-3">
        <span className="h-2 w-2 animate-pulse rounded-full bg-accent" />
        <div>
          <div className="font-medium text-card-foreground">Agent audit log</div>
          <div className="text-xs text-muted-foreground">
            every tool call, bounded &amp; gated — refreshes every 2.5s
          </div>
        </div>
      </div>

      <div className="flex-1 space-y-2 overflow-y-auto p-3">
        {error && <div className="rounded-lg bg-amber-50 p-2 text-xs text-amber-800">{error}</div>}
        {rows.length === 0 && !error && (
          <div className="p-2 text-xs text-muted-foreground">No agent actions yet — send a chat message.</div>
        )}
        {rows.map((r) => (
          <div
            key={r.id}
            className="rounded-lg border border-border p-2.5 text-xs transition hover:border-secondary hover:shadow-sm"
          >
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="font-mono font-medium text-card-foreground">{r.tool}</span>
              <span
                className={`rounded-full px-2 py-0.5 font-medium ${SOURCE_STYLE[r.source] || "bg-muted text-muted-foreground"}`}
              >
                {r.source}
              </span>
            </div>
            <div className={`mb-1 inline-block rounded-full border px-2 py-0.5 ${OUTCOME_STYLE[r.outcome] || ""}`}>
              {r.outcome}
              {r.amount_inr != null && ` · ₹${r.amount_inr}`}
              {r.bound_limit_inr != null && ` / cap ₹${r.bound_limit_inr}`}
            </div>
            {r.order_id && (
              <div className="mb-1 truncate font-mono text-[10px] text-muted-foreground">{r.order_id}</div>
            )}
            <div className="truncate text-muted-foreground">{r.input}</div>
            {r.reason && <div className="mt-0.5 truncate text-muted-foreground">{r.reason}</div>}
            <div className="mt-1 text-[10px] text-muted-foreground">
              {new Date(r.timestamp * 1000).toLocaleTimeString()}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
