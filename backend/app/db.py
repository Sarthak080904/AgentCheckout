"""Single shared SQLite connection + schema for audit log, orders, and pending
upsells. One file, one place new columns/tables get added — audit.py and
orders.py both import connect() from here instead of each managing their own
connection/schema."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "audit.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    session_id TEXT,
    source TEXT NOT NULL DEFAULT 'human-chat',
    tool TEXT NOT NULL,
    input TEXT NOT NULL,
    amount_inr INTEGER,
    bound_limit_inr INTEGER,
    within_bound INTEGER NOT NULL,
    result TEXT NOT NULL,
    outcome TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    session_id TEXT,
    source TEXT NOT NULL DEFAULT 'human-chat',
    sku_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    amount_inr INTEGER NOT NULL,
    razorpay_payment_link_id TEXT,
    kind TEXT NOT NULL DEFAULT 'original',
    parent_order_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL,
    paid_at REAL
);

CREATE TABLE IF NOT EXISTS pending_upsells (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    source_order_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'offered',
    created_at REAL NOT NULL
);

-- Human-chat confirmation gate (section 1): create_payment_link refuses to
-- run unless a row here for the same session_id is 'confirmed' and matches
-- the sku/quantity/amount exactly. Single-use: consumed on success.
CREATE TABLE IF NOT EXISTS pending_confirmations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    sku_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    amount_inr INTEGER NOT NULL,
    product_name TEXT,
    status TEXT NOT NULL DEFAULT 'requested',  -- requested | confirmed | rejected | consumed
    created_at REAL NOT NULL,
    confirmed_at REAL
);

-- Agent-to-agent quote gate (section 2): /api/agent/order requires a
-- quote_id from here, matching exactly and not expired/already consumed.
CREATE TABLE IF NOT EXISTS quotes (
    quote_id TEXT PRIMARY KEY,
    buyer_agent_id TEXT,
    sku_id TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    amount_inr INTEGER NOT NULL,
    within_bound INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',  -- active | consumed
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
"""

# Additive migration for DBs created before order_id/sku_id/reason existed on
# agent_actions. SQLite has no "ADD COLUMN IF NOT EXISTS"; ignore the error if
# the column is already there.
_MIGRATIONS = [
    "ALTER TABLE agent_actions ADD COLUMN order_id TEXT",
    "ALTER TABLE agent_actions ADD COLUMN sku_id TEXT",
    "ALTER TABLE agent_actions ADD COLUMN reason TEXT",
]


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists
    return conn
