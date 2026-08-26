-- The live schema is created automatically by backend/app/audit.py on first run
-- (SQLite, file: backend/data/audit.db) — this file exists purely so the data
-- model is readable without opening the Python source.

CREATE TABLE IF NOT EXISTS agent_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       REAL NOT NULL,          -- unix epoch seconds
    session_id      TEXT,                   -- groups actions from one chat/buyer-agent session
    source          TEXT NOT NULL DEFAULT 'human-chat',  -- 'human-chat' | 'agent-to-agent'
    tool            TEXT NOT NULL,          -- e.g. 'search_catalog', 'create_payment_link'
    input           TEXT NOT NULL,          -- JSON: exact arguments the agent passed
    amount_inr      INTEGER,                -- set only for money-moving tools
    bound_limit_inr INTEGER,                -- the cap that was checked against, if any
    within_bound    INTEGER NOT NULL,       -- 1 = allowed, 0 = blocked by guardrail
    result          TEXT NOT NULL,          -- JSON: what the tool actually returned
    outcome         TEXT NOT NULL           -- 'info' | 'created' | 'blocked_over_limit' | 'error'
);
