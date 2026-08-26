"use client";

import { useState } from "react";
import ChatPanel from "./ChatPanel";
import AuditLogPanel from "./AuditLogPanel";

export default function AgentWorkspace() {
  const [refreshSignal, setRefreshSignal] = useState(0);

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <ChatPanel onActivity={() => setRefreshSignal((n) => n + 1)} />
      <AuditLogPanel refreshSignal={refreshSignal} />
    </div>
  );
}
