from app.catalog import load_catalog, find_product
from app.razorpay_client import create_payment_link
from app.config import AGENT_MAX_AUTO_AMOUNT_INR
from app.audit import log_action

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
        "name": "create_payment_link",
        "description": (
            "Create a Razorpay test-mode payment link for a product so the buyer can complete checkout. "
            "Only call this after the buyer has explicitly confirmed the specific product and quantity they want to buy."
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


def _create_payment_link(tool_input: dict) -> dict:
    sku_id = tool_input["sku_id"]
    quantity = tool_input.get("quantity", 1)
    product = find_product(sku_id)

    if not product:
        return {"error": "not_found", "within_bound": True, "amount_inr": None}
    if product["stock"] < quantity:
        return {"error": "insufficient_stock", "available": product["stock"], "within_bound": True, "amount_inr": None}

    total = product["price_inr"] * quantity

    # Guardrail: agent cannot auto-create a payment above the configured cap.
    # Above this, the tool refuses and asks for a human-confirmed override
    # instead of silently proceeding — this is the "bounded and gated" part.
    if total > AGENT_MAX_AUTO_AMOUNT_INR:
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

    link = create_payment_link(
        amount_inr=total,
        description=f"{quantity} x {product['name']} ({sku_id})",
    )
    return {"payment_link": link, "total_inr": total, "within_bound": True, "amount_inr": total}


_HANDLERS = {
    "search_catalog": _search_catalog,
    "get_product": _get_product,
    "create_payment_link": _create_payment_link,
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

    result = handler(tool_input)

    is_money_action = name == "create_payment_link"
    within_bound = result.get("within_bound", True)
    if "payment_link" in result:
        outcome = "created"
    elif is_money_action and not within_bound:
        outcome = "blocked_over_limit"
    elif "error" in result:
        outcome = "error"
    else:
        outcome = "info"

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
    )
    return result
