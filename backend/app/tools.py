from app.catalog import load_catalog, find_product, validate_quantity
from app.razorpay_client import create_payment_link, fetch_payment_link_status, PaymentLinkError
from app.config import AGENT_MAX_AUTO_AMOUNT_INR
from app.audit import log_action
from app.orders import (
    generate_order_id,
    create_order,
    get_order,
    mark_order_paid,
    mark_order_failed,
    select_upsell,
    create_pending_upsell,
    get_offered_upsell,
    resolve_pending_upsell,
    create_pending_confirmation,
    get_latest_confirmation,
    resolve_confirmation,
    consume_confirmation,
)

TOOL_SCHEMAS = [
    {
        "name": "search_catalog",
        "description": "Search the merchant's product catalog by keyword, category, and/or max price.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keyword to match against product name/description/category."},
                "max_price_inr": {"type": "integer", "description": "Optional upper price bound in INR."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_product",
        "description": "Get full details for one product by its SKU id.",
        "input_schema": {
            "type": "object",
            "properties": {"sku_id": {"type": "string"}},
            "required": ["sku_id"],
        },
    },
    {
        "name": "request_purchase_confirmation",
        "description": (
            "Register a pending purchase with the backend BEFORE asking the buyer to confirm it. Call this "
            "first — it computes the real price from the catalog. Present the returned product name, quantity, "
            "and amount to the buyer verbatim, then wait for their explicit yes/no before calling confirm_purchase."
        ),
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
        "name": "confirm_purchase",
        "description": (
            "Record the buyer's explicit yes/no answer to the purchase you just asked them to confirm. Must "
            "reference the exact same sku_id and quantity you called request_purchase_confirmation with — a "
            "different product or quantity requires a new request_purchase_confirmation first. Only after this "
            "returns status='confirmed' may you call create_payment_link."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sku_id": {"type": "string"},
                "quantity": {"type": "integer", "default": 1},
                "confirmed": {"type": "boolean"},
            },
            "required": ["sku_id", "quantity", "confirmed"],
        },
    },
    {
        "name": "create_payment_link",
        "description": (
            "Create a Razorpay test-mode payment link for a product so the buyer can complete checkout. Requires "
            "a matching, still-valid confirm_purchase(confirmed=true) for this exact sku_id/quantity in this "
            "session — refused otherwise, even if the conversation looks like the buyer already agreed. "
            "This creates a PENDING order — it does not mean the buyer has paid yet."
        ),
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
        "name": "check_order_status",
        "description": (
            "Check whether an order's payment has actually been confirmed by Razorpay. "
            "Returns status: 'pending' | 'paid' | 'failed'. Call this before ever offering an upsell, "
            "and whenever the buyer says they've completed payment."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "offer_upsell",
        "description": (
            "Ask the backend to pick one complementary add-on product for an order. ONLY call this after "
            "check_order_status confirms the order's status is 'paid' — calling it earlier is refused. "
            "Present exactly the product name/price this returns; never substitute a different product."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"order_id": {"type": "string"}},
            "required": ["order_id"],
        },
    },
    {
        "name": "confirm_upsell",
        "description": (
            "Record the buyer's yes/no answer to the upsell that was just offered for this order. "
            "If accepted, creates a separate order and a separate payment link for that exact product "
            "(you cannot pick a different product here — only accept or decline the one already offered)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {"type": "string"},
                "accept": {"type": "boolean"},
            },
            "required": ["order_id", "accept"],
        },
    },
]


def _search_catalog(tool_input: dict) -> dict:
    query = tool_input.get("query", "").lower()
    max_price = tool_input.get("max_price_inr")
    results = []
    for p in load_catalog():
        haystack = f"{p['name']} {p['description']} {p['category']}".lower()
        if query and query not in haystack:
            continue
        if max_price is not None and p["price_inr"] > max_price:
            continue
        results.append(p)
    return {"results": results, "count": len(results)}


def _get_product(tool_input: dict) -> dict:
    product = find_product(tool_input["sku_id"])
    return {"product": product} if product else {"error": "not_found"}


def create_order_and_link(
    *,
    sku_id: str,
    quantity: int,
    session_id: str | None,
    source: str,
    kind: str = "original",
    parent_order_id: str | None = None,
) -> dict:
    """
    The shared core: validate, check the cap, create the Razorpay link, and
    record the order. Used by three different gates, each of which decides
    separately whether it's even allowed to call this:
      - the chat create_payment_link tool (after the confirmation gate below)
      - confirm_upsell's accept path (after the pending-upsell gate)
      - /api/agent/order in main.py (after the quote-token gate)
    Returns a dict that always includes within_bound/amount_inr (for audit
    logging) plus either "payment_link"+"order_id" on success or "error".
    """
    product = find_product(sku_id)
    if not product:
        return {"error": "not_found", "within_bound": True, "amount_inr": None}

    qty_error = validate_quantity(quantity, product["stock"])
    if qty_error:
        return {
            "error": qty_error,
            "available": product["stock"],
            "within_bound": True,
            "amount_inr": None,
        }

    total = product["price_inr"] * quantity

    # Guardrail: never create a payment link above the configured cap,
    # regardless of which gate let the request through. Never send a
    # zero/negative amount to Razorpay either (quantity>=1 and price>0 in the
    # catalog already guarantee total > 0, but the check is cheap insurance).
    if total <= 0 or total > AGENT_MAX_AUTO_AMOUNT_INR:
        return {
            "error": "amount_exceeds_auto_limit",
            "amount_inr": total,
            "limit_inr": AGENT_MAX_AUTO_AMOUNT_INR,
            "within_bound": False,
            "message": (
                f"₹{total} exceeds the ₹{AGENT_MAX_AUTO_AMOUNT_INR} auto-approval limit. "
                "This requires explicit human sign-off outside the agent before proceeding."
            ),
        }

    order_id = generate_order_id()
    try:
        link = create_payment_link(
            amount_inr=total,
            description=f"{quantity} x {product['name']} ({sku_id})",
            notes={"order_id": order_id},
        )
    except PaymentLinkError as e:
        # Genuine runtime failure (network/API), not a policy refusal — this
        # is the "one failure handled gracefully" case: caught here instead
        # of the request 500ing. No order row is created since no payment
        # link actually exists to track.
        return {
            "error": "payment_provider_unavailable",
            "detail": str(e),
            "within_bound": True,
            "amount_inr": total,
            "message": (
                "Razorpay didn't confirm the payment link after retrying. "
                "This looks like a temporary issue on the payment provider's side."
            ),
        }

    create_order(
        order_id=order_id,
        session_id=session_id,
        source=source,
        sku_id=sku_id,
        quantity=quantity,
        amount_inr=total,
        razorpay_payment_link_id=link["id"],
        kind=kind,
        parent_order_id=parent_order_id,
    )

    return {
        "payment_link": link,
        "order_id": order_id,
        "total_inr": total,
        "within_bound": True,
        "amount_inr": total,
    }


_CONFIRMATION_ERRORS = {"confirmation_required", "confirmation_mismatch", "confirmation_already_consumed"}


def _create_payment_link(tool_input: dict, *, session_id: str | None, source: str) -> dict:
    sku_id = tool_input["sku_id"]
    quantity = tool_input.get("quantity", 1)

    # Backend confirmation gate — the ONLY thing that can prove the buyer
    # actually approved this exact product/quantity, independent of whatever
    # the model claims happened in the conversation. This tool is only ever
    # reached from the human-chat loop (agent-to-agent uses the quote-token
    # gate in main.py instead, which calls create_order_and_link directly).
    if not session_id:
        return {"error": "session_required", "within_bound": True, "amount_inr": None}

    pending = get_latest_confirmation(session_id)
    if not pending or pending["status"] != "confirmed":
        return {
            "error": "confirmation_required",
            "within_bound": True,
            "amount_inr": None,
            "message": "No confirmed purchase found for this session — ask the buyer to confirm first.",
        }
    if pending["sku_id"] != sku_id or pending["quantity"] != quantity:
        return {
            "error": "confirmation_mismatch",
            "within_bound": True,
            "amount_inr": None,
            "message": "The confirmed purchase doesn't match this request — a new confirmation is required.",
        }
    if not consume_confirmation(pending["id"]):
        # Single-use: someone already consumed this exact confirmation
        # (e.g. a duplicate/retried tool call) — refuse rather than double-charge.
        return {
            "error": "confirmation_already_consumed",
            "within_bound": True,
            "amount_inr": None,
            "message": "This confirmation has already been used to create a payment link.",
        }

    result = create_order_and_link(sku_id=sku_id, quantity=quantity, session_id=session_id, source=source, kind="original")

    if "payment_link" not in result:
        # Nothing was actually created (e.g. a transient Razorpay failure) —
        # "single-use" means invalidated once a link is created, not burned on
        # a failed attempt. Restore it so the buyer can retry without
        # re-confirming from scratch.
        resolve_confirmation(pending["id"], "confirmed")

    return result


def _request_purchase_confirmation(tool_input: dict, *, session_id: str | None) -> dict:
    if not session_id:
        return {"error": "session_required"}

    sku_id = tool_input["sku_id"]
    quantity = tool_input.get("quantity", 1)
    product = find_product(sku_id)
    if not product:
        return {"error": "not_found"}

    qty_error = validate_quantity(quantity, product["stock"])
    if qty_error:
        return {"error": qty_error, "available": product["stock"]}

    amount = product["price_inr"] * quantity
    confirmation_id = create_pending_confirmation(
        session_id=session_id, sku_id=sku_id, quantity=quantity, amount_inr=amount, product_name=product["name"]
    )
    return {
        "confirmation_id": confirmation_id,
        "sku_id": sku_id,
        "quantity": quantity,
        "amount_inr": amount,
        "product_name": product["name"],
    }


def _confirm_purchase(tool_input: dict, *, session_id: str | None) -> dict:
    if not session_id:
        return {"error": "session_required"}

    sku_id = tool_input["sku_id"]
    quantity = tool_input.get("quantity", 1)
    confirmed = tool_input["confirmed"]

    pending = get_latest_confirmation(session_id)
    if not pending or pending["status"] != "requested":
        return {"error": "no_pending_confirmation"}

    if pending["sku_id"] != sku_id or pending["quantity"] != quantity:
        # Whatever was pending doesn't match what's being confirmed — reject
        # it outright rather than silently confirming the wrong thing.
        resolve_confirmation(pending["id"], "rejected")
        return {
            "error": "confirmation_mismatch",
            "confirmation_id": pending["id"],
            "message": "This doesn't match the product/quantity that was requested for confirmation.",
        }

    if not confirmed:
        resolve_confirmation(pending["id"], "rejected")
        return {"confirmation_id": pending["id"], "status": "rejected", "sku_id": sku_id, "quantity": quantity}

    resolve_confirmation(pending["id"], "confirmed")
    return {
        "confirmation_id": pending["id"],
        "status": "confirmed",
        "sku_id": sku_id,
        "quantity": quantity,
        "amount_inr": pending["amount_inr"],
    }


def _check_order_status(tool_input: dict) -> dict:
    order = get_order(tool_input["order_id"])
    if not order:
        return {"error": "not_found"}

    # Fallback reconciliation: if no webhook has updated this order yet, ask
    # Razorpay directly. Covers local dev/demos with no public URL for
    # Razorpay to deliver a webhook to — the webhook is still the primary
    # mechanism and this is skipped once an order is already resolved.
    if order["status"] == "pending" and order["razorpay_payment_link_id"]:
        remote_status = fetch_payment_link_status(order["razorpay_payment_link_id"])
        changed = False
        if remote_status == "paid":
            changed = mark_order_paid(order["order_id"])
            outcome, reason = "original_payment_completed", "Confirmed by polling Razorpay directly (no webhook received)"
        elif remote_status in ("expired", "cancelled"):
            changed = mark_order_failed(order["order_id"])
            outcome, reason = "original_payment_failed", f"Razorpay reports {remote_status} (polled, no webhook received)"
        else:
            outcome = reason = None

        if changed:
            log_action(
                session_id=order["session_id"],
                source=order["source"],
                tool="reconcile_payment_status",
                tool_input={"order_id": order["order_id"]},
                result={"remote_status": remote_status},
                amount_inr=order["amount_inr"],
                bound_limit_inr=None,
                within_bound=True,
                outcome=outcome,
                order_id=order["order_id"],
                sku_id=order["sku_id"],
                reason=reason,
            )
            order = get_order(order["order_id"])  # re-read the now-updated row

    return {
        "order_id": order["order_id"],
        "status": order["status"],
        "sku_id": order["sku_id"],
        "quantity": order["quantity"],
        "amount_inr": order["amount_inr"],
    }


def _offer_upsell(tool_input: dict, *, session_id: str | None) -> dict:
    order_id = tool_input["order_id"]
    order = get_order(order_id)
    if not order:
        return {"error": "not_found", "order_id": order_id}

    # Backend-enforced gate — even if the model tries this before payment is
    # confirmed, it's refused here, not just discouraged in the prompt.
    if order["status"] != "paid":
        return {
            "error": "payment_not_confirmed",
            "order_id": order_id,
            "status": order["status"],
            "message": "This order's payment hasn't been confirmed yet, so no upsell can be offered.",
        }

    # Idempotent: re-calling this for the same order returns the same
    # already-offered product rather than re-rolling a new one.
    existing = get_offered_upsell(order_id)
    if existing:
        product = find_product(existing["sku_id"])
        return {"order_id": order_id, "offer": product}

    upsell = select_upsell(order["sku_id"])
    if not upsell:
        return {"order_id": order_id, "offer": None, "message": "No suitable add-on for this order."}

    create_pending_upsell(session_id=session_id, source_order_id=order_id, sku_id=upsell["id"])
    return {"order_id": order_id, "offer": upsell}


def _confirm_upsell(tool_input: dict, *, session_id: str | None, source: str) -> dict:
    order_id = tool_input["order_id"]
    accept = tool_input["accept"]

    pending = get_offered_upsell(order_id)
    if not pending:
        return {"error": "no_pending_upsell", "order_id": order_id}

    if not accept:
        resolve_pending_upsell(pending["id"], "declined")
        return {"order_id": order_id, "status": "declined", "sku_id": pending["sku_id"]}

    # The SKU comes ONLY from the stored offer, never from tool_input — the
    # model has no way to substitute a different product at this step.
    result = create_order_and_link(
        sku_id=pending["sku_id"],
        quantity=1,
        session_id=session_id,
        source=source,
        kind="upsell",
        parent_order_id=order_id,
    )
    resolve_pending_upsell(pending["id"], "accepted")
    result["upsell_sku_id"] = pending["sku_id"]
    result["source_order_id"] = order_id
    return result


_HANDLERS = {
    "search_catalog": lambda inp, **ctx: _search_catalog(inp),
    "get_product": lambda inp, **ctx: _get_product(inp),
    "request_purchase_confirmation": lambda inp, **ctx: _request_purchase_confirmation(inp, session_id=ctx["session_id"]),
    "confirm_purchase": lambda inp, **ctx: _confirm_purchase(inp, session_id=ctx["session_id"]),
    "create_payment_link": lambda inp, **ctx: _create_payment_link(inp, session_id=ctx["session_id"], source=ctx["source"]),
    "check_order_status": lambda inp, **ctx: _check_order_status(inp),
    "offer_upsell": lambda inp, **ctx: _offer_upsell(inp, session_id=ctx["session_id"]),
    "confirm_upsell": lambda inp, **ctx: _confirm_upsell(inp, session_id=ctx["session_id"], source=ctx["source"]),
}

# Tools that create a Razorpay payment link — subject to the auto-approval
# cap and logged with amount/bound info in the audit trail.
_MONEY_TOOLS = {"create_payment_link", "confirm_upsell"}

_OUTCOME_BY_TOOL = {
    "check_order_status": "info",
    "offer_upsell": "upsell_offered",
}


def run_tool(name: str, tool_input: dict, *, session_id: str | None = None, source: str = "human-chat") -> dict:
    """
    Single execution + audit-logging path for every tool call, whichever channel
    it came from (the human-facing chat agent in agent.py, or the agent-to-agent
    endpoints in main.py) — so there's exactly one place that can create a payment
    link and exactly one place that writes the audit trail.
    """
    handler = _HANDLERS.get(name)
    if handler is None:
        return {"error": f"unknown_tool:{name}"}

    result = handler(tool_input, session_id=session_id, source=source)

    is_money_action = name in _MONEY_TOOLS
    within_bound = result.get("within_bound", True)

    if name == "request_purchase_confirmation":
        outcome = "purchase_confirmation_requested" if "error" not in result else "error"
    elif name == "confirm_purchase":
        if result.get("status") == "confirmed":
            outcome = "purchase_confirmed"
        elif result.get("status") == "rejected" or "error" in result:
            outcome = "purchase_rejected"
        else:
            outcome = "info"
    elif name == "create_payment_link" and result.get("error") in _CONFIRMATION_ERRORS:
        outcome = "purchase_rejected"
    elif name == "confirm_upsell":
        if "payment_link" in result:
            outcome = "upsell_payment_created" if result.get("status") != "declined" else "upsell_declined"
        elif result.get("status") == "declined":
            outcome = "upsell_declined"
        elif not within_bound:
            outcome = "blocked_over_limit"
        elif "error" in result:
            outcome = "error"
        else:
            outcome = "info"
    elif "payment_link" in result:
        outcome = "created"
    elif is_money_action and not within_bound:
        outcome = "blocked_over_limit"
    elif "error" in result:
        outcome = "error"
    else:
        outcome = _OUTCOME_BY_TOOL.get(name, "info")

    order_id = result.get("order_id") or result.get("source_order_id") or tool_input.get("order_id")
    if order_id is None and result.get("confirmation_id") is not None:
        order_id = f"conf_{result['confirmation_id']}"  # correlation id, reusing the generic column
    sku_id = tool_input.get("sku_id") or result.get("sku_id") or result.get("upsell_sku_id")
    reason = result.get("message")

    log_action(
        session_id=session_id,
        source=source,
        tool=name,
        tool_input=tool_input,
        result=result,
        amount_inr=result.get("amount_inr") if is_money_action else None,
        bound_limit_inr=AGENT_MAX_AUTO_AMOUNT_INR if is_money_action else None,
        within_bound=within_bound,
        outcome=outcome,
        order_id=order_id,
        sku_id=sku_id,
        reason=reason,
    )
    return result
