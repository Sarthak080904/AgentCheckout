"""Order tracking + deterministic upsell selection.

A payment link being created does NOT mean the customer paid — that's only
true once Razorpay's webhook confirms it (see main.py's /api/webhooks/razorpay).
This module is the source of truth for order status in between.
"""

import secrets
import time

from app.catalog import find_product, load_catalog
from app.db import connect

MAX_UPSELL_PRICE_INR = 1000

# Preferred complementary categories; selection falls back to the cheapest match.
_UPSELL_AFFINITY: dict[str, list[str]] = {
    "footwear": ["apparel", "fitness"],
    "electronics": ["bags", "home"],
    "fitness": ["apparel", "home"],
    "apparel": ["fitness", "home"],
    "bags": ["electronics", "apparel"],
    "home": ["apparel", "electronics"],
}


def generate_order_id() -> str:
    return f"ord_{secrets.token_hex(8)}"


def create_order(
    *,
    order_id: str,
    session_id: str | None,
    source: str,
    sku_id: str,
    quantity: int,
    amount_inr: int,
    razorpay_payment_link_id: str | None,
    kind: str = "original",
    parent_order_id: str | None = None,
) -> None:
    conn = connect()
    with conn:
        conn.execute(
            """
            INSERT INTO orders
                (order_id, session_id, source, sku_id, quantity, amount_inr,
                 razorpay_payment_link_id, kind, parent_order_id, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (order_id, session_id, source, sku_id, quantity, amount_inr,
             razorpay_payment_link_id, kind, parent_order_id, time.time()),
        )
    conn.close()


def get_order(order_id: str) -> dict | None:
    conn = connect()
    row = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def find_order_by_payment_link_id(link_id: str) -> dict | None:
    conn = connect()
    row = conn.execute(
        "SELECT * FROM orders WHERE razorpay_payment_link_id = ?", (link_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def mark_order_paid(order_id: str) -> bool:
    """Idempotent: returns True if this call actually changed status to paid
    (i.e. it wasn't already paid) — the caller uses this to detect duplicate
    webhook deliveries and log them distinctly instead of double-processing."""
    conn = connect()
    with conn:
        cur = conn.execute(
            "UPDATE orders SET status = 'paid', paid_at = ? WHERE order_id = ? AND status != 'paid'",
            (time.time(), order_id),
        )
        changed = cur.rowcount > 0
    conn.close()
    return changed


def mark_order_failed(order_id: str) -> bool:
    """Never downgrades an already-paid order — a failed/expired event
    arriving after a paid event (out of order, or a stale retry) must not
    undo a completed payment."""
    conn = connect()
    with conn:
        cur = conn.execute(
            "UPDATE orders SET status = 'failed' WHERE order_id = ? AND status = 'pending'",
            (order_id,),
        )
        changed = cur.rowcount > 0
    conn.close()
    return changed


def select_upsell(original_sku_id: str) -> dict | None:
    """Backend-only, deterministic (no LLM call). Picks at most one product
    that's in stock, a different category, not the same SKU, and <= Rs 1000 —
    preferring a thematically related category, falling back to cheapest."""
    original = find_product(original_sku_id)
    if not original:
        return None

    candidates = [
        p
        for p in load_catalog()
        if p["id"] != original_sku_id
        and p["category"] != original["category"]
        and p["stock"] > 0
        and p["price_inr"] <= MAX_UPSELL_PRICE_INR
    ]
    if not candidates:
        return None

    for preferred_category in _UPSELL_AFFINITY.get(original["category"], []):
        for c in candidates:
            if c["category"] == preferred_category:
                return c

    candidates.sort(key=lambda p: p["price_inr"])
    return candidates[0]


def create_pending_upsell(*, session_id: str | None, source_order_id: str, sku_id: str) -> None:
    conn = connect()
    with conn:
        conn.execute(
            """
            INSERT INTO pending_upsells (session_id, source_order_id, sku_id, status, created_at)
            VALUES (?, ?, ?, 'offered', ?)
            """,
            (session_id, source_order_id, sku_id, time.time()),
        )
    conn.close()


def get_offered_upsell(source_order_id: str) -> dict | None:
    """The current outstanding offer for this order, if any — the exact
    product the customer must confirm. Confirmation never trusts a sku_id
    supplied by the caller/model, only this row."""
    conn = connect()
    row = conn.execute(
        """
        SELECT * FROM pending_upsells
        WHERE source_order_id = ? AND status = 'offered'
        ORDER BY id DESC LIMIT 1
        """,
        (source_order_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def resolve_pending_upsell(pending_id: int, status: str) -> None:
    conn = connect()
    with conn:
        conn.execute("UPDATE pending_upsells SET status = ? WHERE id = ?", (status, pending_id))
    conn.close()


# Human-chat purchase confirmation state.


def create_pending_confirmation(
    *, session_id: str, sku_id: str, quantity: int, amount_inr: int, product_name: str
) -> int:
    conn = connect()
    with conn:
        cur = conn.execute(
            """
            INSERT INTO pending_confirmations
                (session_id, sku_id, quantity, amount_inr, product_name, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'requested', ?)
            """,
            (session_id, sku_id, quantity, amount_inr, product_name, time.time()),
        )
        confirmation_id = cur.lastrowid
    conn.close()
    return confirmation_id


def get_latest_confirmation(session_id: str) -> dict | None:
    """The most recent confirmation row for this session, whatever its
    status — callers check `status` themselves rather than filtering here,
    since e.g. confirm_purchase needs to see 'requested' rows specifically
    while create_payment_link needs to see 'confirmed' ones."""
    conn = connect()
    row = conn.execute(
        "SELECT * FROM pending_confirmations WHERE session_id = ? ORDER BY id DESC LIMIT 1",
        (session_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def resolve_confirmation(confirmation_id: int, status: str) -> None:
    conn = connect()
    with conn:
        conn.execute(
            "UPDATE pending_confirmations SET status = ?, confirmed_at = ? WHERE id = ?",
            (status, time.time(), confirmation_id),
        )
    conn.close()


def consume_confirmation(confirmation_id: int) -> bool:
    """Single-use: only succeeds (and only ever will succeed once) if the row
    is currently 'confirmed'. Returns False if it's already been consumed or
    was never confirmed — the caller must treat that as a hard rejection."""
    conn = connect()
    with conn:
        cur = conn.execute(
            "UPDATE pending_confirmations SET status = 'consumed' WHERE id = ? AND status = 'confirmed'",
            (confirmation_id,),
        )
        changed = cur.rowcount > 0
    conn.close()
    return changed
