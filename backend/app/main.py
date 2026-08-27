import hashlib
import hmac
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.catalog import load_catalog, find_product, validate_quantity
from app.agent import run_agent_turn
from app.audit import list_actions, log_action
from app.tools import run_tool
from app.config import AGENT_MAX_AUTO_AMOUNT_INR, RAZORPAY_WEBHOOK_SECRET
from app.orders import get_order, mark_order_paid, mark_order_failed

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


# --- Razorpay webhook: confirms whether a payment link was actually paid.
# Creating a payment link is NOT the same as being paid — this is the only
# thing that marks an order 'paid', which is what gates the upsell offer.
@app.post("/api/webhooks/razorpay")
async def razorpay_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    if not RAZORPAY_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="RAZORPAY_WEBHOOK_SECRET not configured")

    expected = hmac.new(RAZORPAY_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        # Never trust an invalid webhook: reject before touching any order data.
        log_action(
            session_id=None,
            source="razorpay-webhook",
            tool="webhook",
            tool_input={"signature_present": bool(signature)},
            result={"error": "invalid_signature"},
            amount_inr=None,
            bound_limit_inr=None,
            within_bound=True,
            outcome="invalid_webhook",
            reason="Signature verification failed",
        )
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        payload = json.loads(body)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    event = payload.get("event", "")
    entity = payload.get("payload", {}).get("payment_link", {}).get("entity", {})
    order_id = (entity.get("notes") or {}).get("order_id")
    link_id = entity.get("id")

    if not order_id:
        return {"status": "ignored", "reason": "no order_id in webhook notes"}

    order = get_order(order_id)
    if not order:
        return {"status": "ignored", "reason": "unknown order_id"}

    if event == "payment_link.paid":
        changed = mark_order_paid(order_id)
        log_action(
            session_id=order["session_id"],
            source="razorpay-webhook",
            tool="webhook",
            tool_input={"event": event, "payment_link_id": link_id},
            result={"order_id": order_id},
            amount_inr=order["amount_inr"],
            bound_limit_inr=None,
            within_bound=True,
            outcome="original_payment_completed" if changed else "duplicate_webhook_ignored",
            order_id=order_id,
            sku_id=order["sku_id"],
            reason="Payment confirmed by Razorpay" if changed else "Order already marked paid — duplicate event ignored",
        )
    elif event in ("payment_link.expired", "payment_link.cancelled"):
        changed = mark_order_failed(order_id)
        log_action(
            session_id=order["session_id"],
            source="razorpay-webhook",
            tool="webhook",
            tool_input={"event": event, "payment_link_id": link_id},
            result={"order_id": order_id},
            amount_inr=order["amount_inr"],
            bound_limit_inr=None,
            within_bound=True,
            outcome="original_payment_failed" if changed else "duplicate_webhook_ignored",
            order_id=order_id,
            sku_id=order["sku_id"],
            reason=f"Razorpay reported {event}" if changed else "Order already resolved — duplicate/late event ignored",
        )
    # Other event types (e.g. payment_link.partially_paid) are accepted but
    # not acted on — still return 200 so Razorpay doesn't keep retrying.

    return {"status": "ok"}


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

    qty_error = validate_quantity(req.quantity, product["stock"])
    if qty_error:
        raise HTTPException(status_code=422, detail={"error": qty_error, "available": product["stock"]})

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
    product = find_product(req.sku_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    qty_error = validate_quantity(req.quantity, product["stock"])
    if qty_error:
        raise HTTPException(status_code=422, detail={"error": qty_error, "available": product["stock"]})

    result = run_tool(
        "create_payment_link",
        {"sku_id": req.sku_id, "quantity": req.quantity},
        session_id=f"agent:{req.buyer_agent_id}",
        source="agent-to-agent",
    )
    if "payment_link" not in result:
        raise HTTPException(status_code=422, detail=result)
    return result
