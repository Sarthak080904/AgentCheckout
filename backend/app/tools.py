from app.catalog import load_catalog, find_product
from app.razorpay_client import create_payment_link

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


def run_tool(name: str, tool_input: dict) -> dict:
    if name == "search_catalog":
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

    if name == "get_product":
        product = find_product(tool_input["sku_id"])
        return {"product": product} if product else {"error": "not_found"}

    if name == "create_payment_link":
        sku_id = tool_input["sku_id"]
        quantity = tool_input.get("quantity", 1)
        product = find_product(sku_id)
        if not product:
            return {"error": "not_found"}
        if product["stock"] < quantity:
            return {"error": "insufficient_stock", "available": product["stock"]}
        total = product["price_inr"] * quantity
        link = create_payment_link(
            amount_inr=total,
            description=f"{quantity} x {product['name']} ({sku_id})",
        )
        return {"payment_link": link, "total_inr": total}

    return {"error": f"unknown_tool:{name}"}
