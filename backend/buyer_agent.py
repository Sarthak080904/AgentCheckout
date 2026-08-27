"""
Buyer-agent simulator — a second, independent AI agent that shops with the
AgentCheckout merchant on behalf of a human, using ONLY the machine-readable
/api/agent/* endpoints (never our own chat prompt, never /api/chat).

This is the "sellable to AI buyers" half of the track: it proves the merchant
can be transacted with by an agent that has never seen our internal code, only
this HTTP contract.

Usage:
    python buyer_agent.py "Find me a wireless mouse under 1500 rupees and buy one"
"""

import json
import os
import sys

# Windows' default console codepage (cp1252) can't print the rupee sign our
# tool results contain; force UTF-8 stdout so this doesn't crash mid-demo.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import httpx
from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MERCHANT_API_URL = os.getenv("MERCHANT_API_URL", "http://localhost:8000")
BUYER_AGENT_ID = "buyer-agent-demo-1"

SYSTEM_PROMPT = """You are an autonomous shopping agent acting on behalf of a human buyer.
You do not have direct database access — you can only interact with the merchant
through its agent API tools (browse_catalog, get_quote, place_order).

Process:
1. Call browse_catalog to find products matching the buyer's request.
2. Pick the single best match. If several are equally good, pick the first in stock.
3. Call get_quote to confirm price and whether it's within the merchant's auto-approval bound.
   It returns a quote_id — the merchant requires this exact quote_id to place the order, and
   it expires after 2 minutes, so place_order right away rather than waiting.
4. If within_auto_approval_bound is true, call place_order with the SAME sku_id, quantity, and
   quote_id from that quote — a mismatched or missing quote_id will be rejected.
5. If it's false, do NOT place the order — report back that this order needs human approval.

Be decisive: you're acting autonomously, not asking the buyer follow-up questions.
End with a short plain-English summary of what you did and the outcome.
"""

TOOL_SCHEMAS = [
    {
        "name": "browse_catalog",
        "description": "Fetch the merchant's full agent-readable catalog.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_quote",
        "description": "Get a price quote and auto-approval status for a specific product.",
        "input_schema": {
            "type": "object",
            "properties": {
                "sku_id": {"type": "string"},
                "quantity": {"type": "integer", "default": 1},
            },
            "required": ["sku_id"],
        },
    },
    {
        "name": "place_order",
        "description": (
            "Place the order and get a Razorpay test-mode payment link. Only call after a quote confirms "
            "within_auto_approval_bound is true. Requires the exact quote_id from that quote — the merchant "
            "rejects orders with a missing, expired, reused, or mismatched quote_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sku_id": {"type": "string"},
                "quantity": {"type": "integer", "default": 1},
                "quote_id": {"type": "string"},
            },
            "required": ["sku_id", "quote_id"],
        },
    },
]


def run_tool(name: str, tool_input: dict) -> dict:
    with httpx.Client(timeout=15) as client:
        if name == "browse_catalog":
            resp = client.get(f"{MERCHANT_API_URL}/api/agent/catalog")
        elif name == "get_quote":
            resp = client.post(f"{MERCHANT_API_URL}/api/agent/quote", json=tool_input)
        elif name == "place_order":
            resp = client.post(
                f"{MERCHANT_API_URL}/api/agent/order",
                json={**tool_input, "buyer_agent_id": BUYER_AGENT_ID},
            )
        else:
            return {"error": f"unknown_tool:{name}"}

    try:
        return resp.json()
    except ValueError:
        return {"error": "non_json_response", "status_code": resp.status_code, "text": resp.text}


def run_buyer_agent(request_text: str) -> None:
    if not ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in backend/.env")

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    messages = [{"role": "user", "content": request_text}]

    print(f"[buyer-agent] request: {request_text}")
    print(f"[buyer-agent] talking to merchant at {MERCHANT_API_URL}\n")

    for _ in range(6):
        response = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            final_text = "".join(b.text for b in response.content if b.type == "text")
            print(f"\n[buyer-agent] done: {final_text}")
            return

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"[buyer-agent] -> {block.name}({json.dumps(block.input)})")
            result = run_tool(block.name, block.input)
            print(f"[buyer-agent] <- {json.dumps(result)[:300]}")
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(result)})

        messages.append({"role": "user", "content": tool_results})

    print("[buyer-agent] stopped: too many steps without resolving.")


if __name__ == "__main__":
    request = " ".join(sys.argv[1:]) or "Find me a wireless mouse under 1500 rupees and buy one."
    run_buyer_agent(request)
