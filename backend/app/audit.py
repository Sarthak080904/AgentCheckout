import json
import time

from app.db import connect


def log_action(
    *,
    session_id: str | None,
    source: str = "human-chat",  # 'human-chat' | 'agent-to-agent'
    tool: str,
    tool_input: dict,
    result: dict,
    amount_inr: int | None,
    bound_limit_inr: int | None,
    within_bound: bool,
    outcome: str,
    order_id: str | None = None,
    sku_id: str | None = None,
    reason: str | None = None,
) -> None:
    conn = connect()
    with conn:
        conn.execute(
            """
            INSERT INTO agent_actions
                (timestamp, session_id, source, tool, input, amount_inr, bound_limit_inr,
                 within_bound, result, outcome, order_id, sku_id, reason)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                time.time(),
                session_id,
                source,
                tool,
                json.dumps(tool_input),
                amount_inr,
                bound_limit_inr,
                1 if within_bound else 0,
                json.dumps(result, default=str),
                outcome,
                order_id,
                sku_id,
                reason,
            ),
        )
    conn.close()


def list_actions(limit: int = 100) -> list[dict]:
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM agent_actions ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
