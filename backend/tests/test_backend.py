"""
Backend tests for order tracking, the Razorpay webhook, quantity validation,
and the backend-enforced upsell flow. Never calls the real Razorpay API —
create_payment_link is monkeypatched to a fake that returns a fixed dict.
"""

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from app import db as db_module
from app import main as main_module
from app import tools as tools_module
from app.main import app
from app.orders import get_offered_upsell, get_order

TEST_CAP_INR = 2000
TEST_WEBHOOK_SECRET = "whsec_test_secret"

_fake_link_counter = {"n": 0}
_fake_remote_status = {"value": None}  # None = default mock behavior below


def _fake_create_payment_link(*, amount_inr, description, notes=None, customer_name="AgentCheckout Buyer", max_attempts=2):
    _fake_link_counter["n"] += 1
    return {
        "id": f"plink_fake{_fake_link_counter['n']}",
        "short_url": f"https://rzp.io/rzp/fake{_fake_link_counter['n']}",
        "status": "created",
        "amount_inr": amount_inr,
    }


def _fake_fetch_payment_link_status(link_id: str):
    # Default: "still pending" (None -> treated as unknown by the caller),
    # unless a test opts into simulating a specific remote status.
    return _fake_remote_status["value"]


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Fresh SQLite DB per test, fixed cap, fake payment-link creation, no
    real Razorpay network calls, and a known webhook secret."""
    monkeypatch.setattr(db_module, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(tools_module, "AGENT_MAX_AUTO_AMOUNT_INR", TEST_CAP_INR)
    monkeypatch.setattr(main_module, "AGENT_MAX_AUTO_AMOUNT_INR", TEST_CAP_INR)
    monkeypatch.setattr(main_module, "RAZORPAY_WEBHOOK_SECRET", TEST_WEBHOOK_SECRET)
    monkeypatch.setattr(tools_module, "create_payment_link", _fake_create_payment_link)
    monkeypatch.setattr(tools_module, "fetch_payment_link_status", _fake_fetch_payment_link_status)
    _fake_link_counter["n"] = 0
    _fake_remote_status["value"] = None
    yield


@pytest.fixture
def client():
    return TestClient(app)


def sign(body: bytes, secret: str = TEST_WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def webhook_payload(order_id: str, link_id: str, event: str) -> dict:
    return {
        "event": event,
        "payload": {
            "payment_link": {
                "entity": {
                    "id": link_id,
                    "notes": {"order_id": order_id},
                }
            }
        },
    }


# --- A/H: order creation, quantity validation, cap enforcement ---------------


def test_valid_order_creates_pending_order():
    result = tools_module.run_tool("create_payment_link", {"sku_id": "sku-006", "quantity": 1})
    assert "payment_link" in result
    order = get_order(result["order_id"])
    assert order["status"] == "pending"
    assert order["sku_id"] == "sku-006"
    assert order["razorpay_payment_link_id"] == result["payment_link"]["id"]


def test_zero_quantity_rejected():
    result = tools_module.run_tool("create_payment_link", {"sku_id": "sku-006", "quantity": 0})
    assert result.get("error") == "invalid_quantity"
    assert "payment_link" not in result


def test_negative_quantity_rejected():
    result = tools_module.run_tool("create_payment_link", {"sku_id": "sku-006", "quantity": -1})
    assert result.get("error") == "invalid_quantity"


def test_over_stock_quantity_rejected():
    # sku-004 has stock: 5 in the seed catalog
    result = tools_module.run_tool("create_payment_link", {"sku_id": "sku-004", "quantity": 999})
    assert result.get("error") == "insufficient_stock"


def test_over_cap_order_blocked():
    # sku-001 costs 2799 > TEST_CAP_INR (2000)
    result = tools_module.run_tool("create_payment_link", {"sku_id": "sku-001", "quantity": 1})
    assert result.get("error") == "amount_exceeds_auto_limit"
    assert result["within_bound"] is False


def test_agent_quote_rejects_zero_quantity(client):
    res = client.post("/api/agent/quote", json={"sku_id": "sku-006", "quantity": 0})
    assert res.status_code == 422


def test_agent_quote_rejects_over_stock(client):
    res = client.post("/api/agent/quote", json={"sku_id": "sku-004", "quantity": 999})
    assert res.status_code == 422


def test_agent_order_rejects_negative_quantity(client):
    res = client.post("/api/agent/order", json={"sku_id": "sku-006", "quantity": -1, "buyer_agent_id": "test"})
    assert res.status_code == 422


def test_agent_order_over_cap_returns_422(client):
    res = client.post("/api/agent/order", json={"sku_id": "sku-001", "quantity": 1, "buyer_agent_id": "test"})
    assert res.status_code == 422


# --- B/C: webhook signature verification, order mapping, idempotency --------


def test_webhook_valid_signature_marks_order_paid(client):
    order_result = tools_module.run_tool("create_payment_link", {"sku_id": "sku-006", "quantity": 1})
    order_id = order_result["order_id"]
    link_id = order_result["payment_link"]["id"]

    body = json.dumps(webhook_payload(order_id, link_id, "payment_link.paid")).encode()
    res = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": sign(body), "Content-Type": "application/json"},
    )
    assert res.status_code == 200
    assert get_order(order_id)["status"] == "paid"


def test_webhook_invalid_signature_rejected(client):
    order_result = tools_module.run_tool("create_payment_link", {"sku_id": "sku-006", "quantity": 1})
    order_id = order_result["order_id"]
    link_id = order_result["payment_link"]["id"]

    body = json.dumps(webhook_payload(order_id, link_id, "payment_link.paid")).encode()
    res = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": "not-the-real-signature", "Content-Type": "application/json"},
    )
    assert res.status_code == 400
    # Order must NOT have been marked paid by an unverified webhook.
    assert get_order(order_id)["status"] == "pending"


def test_webhook_duplicate_event_is_safely_ignored(client):
    order_result = tools_module.run_tool("create_payment_link", {"sku_id": "sku-006", "quantity": 1})
    order_id = order_result["order_id"]
    link_id = order_result["payment_link"]["id"]
    body = json.dumps(webhook_payload(order_id, link_id, "payment_link.paid")).encode()
    headers = {"X-Razorpay-Signature": sign(body), "Content-Type": "application/json"}

    first = client.post("/api/webhooks/razorpay", content=body, headers=headers)
    second = client.post("/api/webhooks/razorpay", content=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200  # still accepted, not an error — just a no-op
    order = get_order(order_id)
    assert order["status"] == "paid"  # unchanged by the duplicate, not double-processed


def test_webhook_failed_event_marks_order_failed(client):
    order_result = tools_module.run_tool("create_payment_link", {"sku_id": "sku-006", "quantity": 1})
    order_id = order_result["order_id"]
    link_id = order_result["payment_link"]["id"]

    body = json.dumps(webhook_payload(order_id, link_id, "payment_link.expired")).encode()
    res = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": sign(body), "Content-Type": "application/json"},
    )
    assert res.status_code == 200
    assert get_order(order_id)["status"] == "failed"


def test_webhook_failed_event_does_not_downgrade_paid_order(client):
    order_result = tools_module.run_tool("create_payment_link", {"sku_id": "sku-006", "quantity": 1})
    order_id = order_result["order_id"]
    link_id = order_result["payment_link"]["id"]
    paid_body = json.dumps(webhook_payload(order_id, link_id, "payment_link.paid")).encode()
    client.post(
        "/api/webhooks/razorpay",
        content=paid_body,
        headers={"X-Razorpay-Signature": sign(paid_body), "Content-Type": "application/json"},
    )

    expired_body = json.dumps(webhook_payload(order_id, link_id, "payment_link.expired")).encode()
    client.post(
        "/api/webhooks/razorpay",
        content=expired_body,
        headers={"X-Razorpay-Signature": sign(expired_body), "Content-Type": "application/json"},
    )

    assert get_order(order_id)["status"] == "paid"  # a late/stale "expired" can't undo a paid order


# --- D/E: backend-enforced, deterministic upsell flow -----------------------


def _create_and_pay(sku_id: str, session_id: str = "sess-1") -> str:
    order_result = tools_module.run_tool(
        "create_payment_link", {"sku_id": sku_id, "quantity": 1}, session_id=session_id
    )
    order_id = order_result["order_id"]
    from app.orders import mark_order_paid

    mark_order_paid(order_id)
    return order_id


def test_no_upsell_before_payment():
    order_result = tools_module.run_tool("create_payment_link", {"sku_id": "sku-003", "quantity": 1})
    order_id = order_result["order_id"]  # still pending, never paid

    result = tools_module.run_tool("offer_upsell", {"order_id": order_id})
    assert result.get("error") == "payment_not_confirmed"


def test_upsell_offered_after_payment():
    order_id = _create_and_pay("sku-003")  # electronics
    result = tools_module.run_tool("offer_upsell", {"order_id": order_id})
    assert "error" not in result
    assert result["offer"] is not None


def test_upsell_is_different_category_and_not_same_sku():
    order_id = _create_and_pay("sku-003")  # electronics
    result = tools_module.run_tool("offer_upsell", {"order_id": order_id})
    offer = result["offer"]
    assert offer["id"] != "sku-003"
    assert offer["category"] != "electronics"
    assert offer["price_inr"] <= 1000
    assert offer["stock"] > 0


def test_explicit_upsell_confirmation_required_and_locked_to_offered_sku():
    order_id = _create_and_pay("sku-003")
    offer = tools_module.run_tool("offer_upsell", {"order_id": order_id})["offer"]

    pending = get_offered_upsell(order_id)
    assert pending["sku_id"] == offer["id"]

    # Declining does not create a payment link.
    declined = tools_module.run_tool("confirm_upsell", {"order_id": order_id, "accept": False})
    assert declined["status"] == "declined"
    assert "payment_link" not in declined


def test_upsell_accept_creates_separate_order_and_payment_link():
    order_id = _create_and_pay("sku-003")
    offer = tools_module.run_tool("offer_upsell", {"order_id": order_id})["offer"]

    accepted = tools_module.run_tool("confirm_upsell", {"order_id": order_id, "accept": True})
    assert "payment_link" in accepted
    assert accepted["source_order_id"] == order_id
    assert accepted["order_id"] != order_id  # a genuinely separate order

    upsell_order = get_order(accepted["order_id"])
    assert upsell_order["kind"] == "upsell"
    assert upsell_order["parent_order_id"] == order_id
    assert upsell_order["sku_id"] == offer["id"]


def test_confirm_upsell_ignores_any_sku_supplied_by_caller():
    """Even if a caller/model tries to slip in a different sku_id, confirm_upsell
    doesn't accept one at all — it only ever uses the stored offer."""
    order_id = _create_and_pay("sku-003")
    tools_module.run_tool("offer_upsell", {"order_id": order_id})

    # confirm_upsell's schema has no sku_id field — passing one is simply ignored.
    result = tools_module.run_tool(
        "confirm_upsell", {"order_id": order_id, "accept": True, "sku_id": "sku-009"}
    )
    upsell_order = get_order(result["order_id"])
    assert upsell_order["sku_id"] != "sku-009"


# --- reconciliation fallback: no webhook received, poll Razorpay directly ---


def test_check_order_status_polls_razorpay_when_no_webhook_received():
    order_result = tools_module.run_tool("create_payment_link", {"sku_id": "sku-006", "quantity": 1})
    order_id = order_result["order_id"]
    assert get_order(order_id)["status"] == "pending"

    _fake_remote_status["value"] = "paid"  # simulate Razorpay reporting paid
    result = tools_module.run_tool("check_order_status", {"order_id": order_id})

    assert result["status"] == "paid"
    assert get_order(order_id)["status"] == "paid"


def test_check_order_status_leaves_pending_when_remote_is_also_pending():
    order_result = tools_module.run_tool("create_payment_link", {"sku_id": "sku-006", "quantity": 1})
    order_id = order_result["order_id"]

    _fake_remote_status["value"] = "created"  # Razorpay's "not yet paid" status
    result = tools_module.run_tool("check_order_status", {"order_id": order_id})

    assert result["status"] == "pending"
