import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "audit.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
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
        )
        """
    )
    return conn


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
) -> None:
    conn = _connect()
    with conn:
        conn.execute(
            """
            INSERT INTO agent_actions
                (timestamp, session_id, source, tool, input, amount_inr, bound_limit_inr, within_bound, result, outcome)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ),
        )
    conn.close()


def list_actions(limit: int = 100) -> list[dict]:
    conn = _connect()
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM agent_actions ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
