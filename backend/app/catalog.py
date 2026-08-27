import json
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "catalog.json"


def load_catalog() -> list[dict]:
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


def find_product(sku_id: str) -> dict | None:
    for item in load_catalog():
        if item["id"] == sku_id:
            return item
    return None


def validate_quantity(quantity: int, stock: int) -> str | None:
    """Shared by /api/agent/quote, /api/agent/order, create_payment_link, and
    chat purchases (which all funnel through create_payment_link). Returns an
    error code, or None if the quantity is valid."""
    if quantity <= 0:
        return "invalid_quantity"
    if quantity > stock:
        return "insufficient_stock"
    return None
