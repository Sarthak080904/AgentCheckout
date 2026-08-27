"""Server-issued quote tokens for the agent-to-agent flow (section 2).

/api/agent/quote snapshots a sku/quantity/amount/cap-status server-side and
hands back a quote_id. /api/agent/order requires that exact quote_id and
rejects anything missing, expired, already-consumed, or that doesn't match
the quoted sku/quantity — a buyer agent can't just call order with whatever
numbers it wants.
"""

import secrets
import time

from app.db import connect

QUOTE_TTL_SECONDS = 120


def generate_quote_id() -> str:
    return f"qte_{secrets.token_hex(8)}"


def create_quote(
    *, buyer_agent_id: str | None, sku_id: str, quantity: int, amount_inr: int, within_bound: bool
) -> dict:
    quote_id = generate_quote_id()
    now = time.time()
    conn = connect()
    with conn:
        conn.execute(
            """
            INSERT INTO quotes
                (quote_id, buyer_agent_id, sku_id, quantity, amount_inr, within_bound, status, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (quote_id, buyer_agent_id, sku_id, quantity, amount_inr, 1 if within_bound else 0, now, now + QUOTE_TTL_SECONDS),
        )
    conn.close()
    return {"quote_id": quote_id, "created_at": now, "expires_at": now + QUOTE_TTL_SECONDS}


def get_quote(quote_id: str) -> dict | None:
    conn = connect()
    row = conn.execute("SELECT * FROM quotes WHERE quote_id = ?", (quote_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def consume_quote(quote_id: str) -> bool:
    """Single-use: only succeeds if the quote is currently 'active' (not
    already consumed by an earlier order)."""
    conn = connect()
    with conn:
        cur = conn.execute(
            "UPDATE quotes SET status = 'consumed' WHERE quote_id = ? AND status = 'active'",
            (quote_id,),
        )
        changed = cur.rowcount > 0
    conn.close()
    return changed
