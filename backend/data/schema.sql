-- The live schema is created automatically by backend/app/db.py on first run
-- (SQLite, file: backend/data/audit.db) — this file exists purely so the data
-- model is readable without opening the Python source.

CREATE TABLE IF NOT EXISTS agent_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       REAL NOT NULL,          -- unix epoch seconds
    session_id      TEXT,                   -- groups actions from one chat/buyer-agent session
    source          TEXT NOT NULL DEFAULT 'human-chat',  -- 'human-chat' | 'agent-to-agent' | 'razorpay-webhook'
    tool            TEXT NOT NULL,          -- e.g. 'search_catalog', 'create_payment_link', 'webhook'
    input           TEXT NOT NULL,          -- JSON: exact arguments the agent/webhook passed
    amount_inr      INTEGER,                -- set only for money-moving tools
    bound_limit_inr INTEGER,                -- the cap that was checked against, if any
    within_bound    INTEGER NOT NULL,       -- 1 = allowed, 0 = blocked by guardrail
    result          TEXT NOT NULL,          -- JSON: what the tool actually returned
    outcome         TEXT NOT NULL,          -- see outcomes list below
    order_id        TEXT,                   -- the order this action relates to, if any
    sku_id          TEXT,                   -- the product this action relates to, if any
    reason          TEXT                    -- human-readable explanation, if any
);
-- outcome values: 'info' | 'created' | 'blocked_over_limit' | 'error' |
--   'original_payment_completed' | 'original_payment_failed' |
--   'upsell_offered' | 'upsell_declined' | 'upsell_payment_created' |
--   'duplicate_webhook_ignored' | 'invalid_webhook'

CREATE TABLE IF NOT EXISTS orders (
    order_id                  TEXT PRIMARY KEY,       -- e.g. 'ord_<16 hex chars>'
    session_id                TEXT,
    source                    TEXT NOT NULL DEFAULT 'human-chat',
    sku_id                    TEXT NOT NULL,
    quantity                  INTEGER NOT NULL,
    amount_inr                INTEGER NOT NULL,
    razorpay_payment_link_id  TEXT,
    kind                      TEXT NOT NULL DEFAULT 'original',  -- 'original' | 'upsell'
    parent_order_id           TEXT,                    -- set on upsell orders, points at the original
    status                    TEXT NOT NULL DEFAULT 'pending',   -- 'pending' | 'paid' | 'failed'
    created_at                REAL NOT NULL,
    paid_at                   REAL
);

CREATE TABLE IF NOT EXISTS pending_upsells (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id       TEXT,
    source_order_id  TEXT NOT NULL,          -- the paid order this upsell was offered against
    sku_id           TEXT NOT NULL,          -- the exact product offered (confirmation can't change this)
    status           TEXT NOT NULL DEFAULT 'offered',  -- 'offered' | 'accepted' | 'declined'
    created_at       REAL NOT NULL
);
