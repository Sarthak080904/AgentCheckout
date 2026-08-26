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
