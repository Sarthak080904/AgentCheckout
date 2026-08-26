from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.catalog import load_catalog, find_product
from app.agent import run_agent_turn
from app.audit import list_actions
from app.tools import run_tool
from app.config import AGENT_MAX_AUTO_AMOUNT_INR

app = FastAPI(title="AgentCheckout API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/catalog")
def get_catalog():
    return load_catalog()


@app.get("/api/catalog/{sku_id}")
def get_product(sku_id: str):
    product = find_product(sku_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


class ChatRequest(BaseModel):
    history: list[dict]  # full prior conversation, e.g. [{"role": "user", "content": "..."}]
    session_id: str | None = None


@app.post("/api/chat")
def chat(req: ChatRequest):
    try:
        result = run_agent_turn(req.history, session_id=req.session_id)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"reply": result["reply"], "messages": result["messages"], "actions": result["actions"]}


@app.get("/api/audit-log")
def audit_log(limit: int = 100):
    return list_actions(limit=limit)


# --- Day 5: agent-readable endpoints, meant to be consumed by ANOTHER AI agent
# (not a human, not our own chat agent) acting on a buyer's behalf. No LLM call
# happens on this side for these — they're plain structured endpoints, which is
# the point: a buyer-agent shouldn't need to understand our chat prompt, just
# this contract. See backend/buyer_agent.py for a working buyer-side agent that
# consumes exactly this API.


@app.get("/api/agent/catalog")
def agent_catalog():
    """Machine-readable storefront description for an external buying agent."""
    return {
        "protocol": "agentcheckout-v1",
        "merchant": "AgentCheckout Demo Store",
        "currency": "INR",
        "products": load_catalog(),
        "endpoints": {
            "quote": {"method": "POST", "path": "/api/agent/quote", "body": {"sku_id": "string", "quantity": "integer"}},
            "order": {"method": "POST", "path": "/api/agent/order", "body": {"sku_id": "string", "quantity": "integer", "buyer_agent_id": "string"}},
        },
        "notes": "orders above the merchant's auto-approval cap are refused by /api/agent/order; check the quote response's within_bound field first.",
    }


class QuoteRequest(BaseModel):
    sku_id: str
    quantity: int = 1


@app.post("/api/agent/quote")
def agent_quote(req: QuoteRequest):
    product = find_product(req.sku_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    total = product["price_inr"] * req.quantity
    return {
        "sku_id": req.sku_id,
        "unit_price_inr": product["price_inr"],
        "quantity": req.quantity,
        "total_inr": total,
        "in_stock": product["stock"] >= req.quantity,
        "within_auto_approval_bound": total <= AGENT_MAX_AUTO_AMOUNT_INR,
        "bound_limit_inr": AGENT_MAX_AUTO_AMOUNT_INR,
    }


class AgentOrderRequest(BaseModel):
    sku_id: str
    quantity: int = 1
    buyer_agent_id: str


@app.post("/api/agent/order")
def agent_order(req: AgentOrderRequest):
    result = run_tool(
        "create_payment_link",
        {"sku_id": req.sku_id, "quantity": req.quantity},
        session_id=f"agent:{req.buyer_agent_id}",
        source="agent-to-agent",
    )
    if "payment_link" not in result:
        raise HTTPException(status_code=422, detail=result)
    return result
