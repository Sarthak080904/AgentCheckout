"""
Backend tests for order tracking, the Razorpay webhook, quantity/cap
validation, the backend-enforced human-chat confirmation gate, the
agent-to-agent quote gate, and the backend-enforced upsell flow.

Never calls the real Razorpay API — create_payment_link is monkeypatched to
a fake that returns a fixed dict and records every call it received.
"""

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from app import db as db_module
from app import main as main_module
from app import tools as tools_module
from app.db import connect
from app.main import app
from app.orders import get_offered_upsell, get_order, mark_order_paid

TEST_CAP_INR = 2000
TEST_WEBHOOK_SECRET = "whsec_test_secret"

_fake_link_counter = {"n": 0}
_fake_remote_status = {"value": None}  # None = default mock behavior below
_fake_link_calls: list[int] = []  # every amount_inr the fake was ever called with


def _fake_create_payment_link(*, amount_inr, description, notes=None, customer_name="AgentCheckout Buyer", max_attempts=2):
    _fake_link_counter["n"] += 1
    _fake_link_calls.append(amount_inr)
    return {
        "id": f"plink_fake{_fake_link_counter['n']}",
        "short_url": f"https://rzp.io/rzp/fake{_fake_link_counter['n']}",
        "status": "created",
        "amount_inr": amount_inr,
    }


def _fake_fetch_payment_link_status(link_id: str):
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
    _fake_link_calls.clear()
    yield


@pytest.fixture
def client():
    return TestClient(app)


def sign(body: bytes, secret: str = TEST_WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def webhook_payload(order_id: str, link_id: str, event: str) -> dict:
    return {
        "event": event,
        "payload": {"payment_link": {"entity": {"id": link_id, "notes": {"order_id": order_id}}}},
    }


# --- human-chat confirmation gate helpers ------------------------------------


def _request_confirmation(sku_id: str, quantity: int = 1, session_id: str = "sess-1") -> dict:
    return tools_module.run_tool(
        "request_purchase_confirmation", {"sku_id": sku_id, "quantity": quantity}, session_id=session_id
    )


def _confirm(sku_id: str, quantity: int = 1, confirmed: bool = True, session_id: str = "sess-1") -> dict:
    return tools_module.run_tool(
        "confirm_purchase",
        {"sku_id": sku_id, "quantity": quantity, "confirmed": confirmed},
        session_id=session_id,
    )


def _buy(sku_id: str, quantity: int = 1, session_id: str = "sess-1") -> dict:
    """Full, correctly-ordered human-chat purchase: request -> confirm -> create link."""
    _request_confirmation(sku_id, quantity, session_id)
    _confirm(sku_id, quantity, True, session_id)
    return tools_module.run_tool("create_payment_link", {"sku_id": sku_id, "quantity": quantity}, session_id=session_id)


def _create_and_pay(sku_id: str, session_id: str = "sess-1") -> str:
    result = _buy(sku_id, 1, session_id)
    order_id = result["order_id"]
    mark_order_paid(order_id)
    return order_id


# --- Section 1: human-chat confirmation gate --------------------------------


def test_payment_rejected_without_any_confirmation():
    result = tools_module.run_tool("create_payment_link", {"sku_id": "sku-006", "quantity": 1}, session_id="sess-1")
    assert result.get("error") == "confirmation_required"
    assert "payment_link" not in result
    assert _fake_link_counter["n"] == 0  # Razorpay was never even called


def test_correct_confirmation_allows_payment_creation():
    result = _buy("sku-006", 1, "sess-1")
    assert "payment_link" in result
    order = get_order(result["order_id"])
    assert order["status"] == "pending"
    assert order["sku_id"] == "sku-006"


def test_confirmation_for_sku_a_cannot_authorize_sku_b():
    _request_confirmation("sku-006", 1, "sess-1")
    _confirm("sku-006", 1, True, "sess-1")
    # Try to spend that confirmed slot on a different SKU.
    result = tools_module.run_tool("create_payment_link", {"sku_id": "sku-003", "quantity": 1}, session_id="sess-1")
    assert result.get("error") == "confirmation_mismatch"
    assert "payment_link" not in result


def test_confirmation_for_quantity_1_cannot_authorize_quantity_2():
    _request_confirmation("sku-006", 1, "sess-1")
    _confirm("sku-006", 1, True, "sess-1")
    result = tools_module.run_tool("create_payment_link", {"sku_id": "sku-006", "quantity": 2}, session_id="sess-1")
    assert result.get("error") == "confirmation_mismatch"


def test_confirmation_is_single_use():
    _request_confirmation("sku-006", 1, "sess-1")
    _confirm("sku-006", 1, True, "sess-1")

    first = tools_module.run_tool("create_payment_link", {"sku_id": "sku-006", "quantity": 1}, session_id="sess-1")
    assert "payment_link" in first

    # Same confirmation, tried again — must not create a second payment link.
    second = tools_module.run_tool("create_payment_link", {"sku_id": "sku-006", "quantity": 1}, session_id="sess-1")
    assert second.get("error") == "confirmation_required"


def test_declined_confirmation_blocks_payment_creation():
    _request_confirmation("sku-006", 1, "sess-1")
    declined = _confirm("sku-006", 1, False, "sess-1")
    assert declined["status"] == "rejected"

    result = tools_module.run_tool("create_payment_link", {"sku_id": "sku-006", "quantity": 1}, session_id="sess-1")
    assert result.get("error") == "confirmation_required"


def test_confirm_purchase_rejects_mismatched_sku_at_confirm_time():
    _request_confirmation("sku-006", 1, "sess-1")
    result = _confirm("sku-003", 1, True, "sess-1")  # different sku than what was requested
    assert result.get("error") == "confirmation_mismatch"


def test_confirmation_scoped_per_session():
    """Confirming in one session must not authorize a payment in another."""
    _request_confirmation("sku-006", 1, "sess-A")
    _confirm("sku-006", 1, True, "sess-A")

    result = tools_module.run_tool("create_payment_link", {"sku_id": "sku-006", "quantity": 1}, session_id="sess-B")
    assert result.get("error") == "confirmation_required"


# --- Section 3: quantity / amount validation (backend-level, chat path) -----


def test_request_confirmation_rejects_zero_quantity():
    result = _request_confirmation("sku-006", 0, "sess-1")
    assert result.get("error") == "invalid_quantity"


def test_request_confirmation_rejects_negative_quantity():
    result = _request_confirmation("sku-006", -1, "sess-1")
    assert result.get("error") == "invalid_quantity"


def test_request_confirmation_rejects_over_stock():
    # sku-004 has stock: 5 in the seed catalog
    result = _request_confirmation("sku-004", 999, "sess-1")
    assert result.get("error") == "insufficient_stock"


def test_over_cap_order_blocked_and_logged():
    # sku-001 costs 2799 > TEST_CAP_INR (2000)
    result = _buy("sku-001", 1, "sess-1")
    assert result.get("error") == "amount_exceeds_auto_limit"
    assert result["within_bound"] is False

    conn = connect()
    row = conn.execute(
        "SELECT * FROM agent_actions WHERE outcome = 'blocked_over_limit' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["sku_id"] == "sku-001"


def test_no_invalid_amount_ever_sent_to_razorpay():
    calls_before = len(_fake_link_calls)
    _request_confirmation("sku-006", 0, "sess-1")  # invalid, rejected before any link attempt
    tools_module.run_tool("create_payment_link", {"sku_id": "sku-006", "quantity": 1}, session_id="sess-1")  # no confirmation
    assert len(_fake_link_calls) == calls_before  # fake Razorpay was never invoked
    assert all(amount > 0 for amount in _fake_link_calls)  # and every real call so far was positive


def test_agent_quote_rejects_zero_quantity(client):
    res = client.post("/api/agent/quote", json={"sku_id": "sku-006", "quantity": 0})
    assert res.status_code == 400


def test_agent_quote_rejects_over_stock(client):
    res = client.post("/api/agent/quote", json={"sku_id": "sku-004", "quantity": 999})
    assert res.status_code == 422


# --- Section 2: agent-to-agent quote/approval gate --------------------------


def test_valid_quote_allows_agent_to_agent_ordering(client):
    quote = client.post("/api/agent/quote", json={"sku_id": "sku-006", "quantity": 1, "buyer_agent_id": "buyer-1"}).json()
    res = client.post(
        "/api/agent/order",
        json={"sku_id": "sku-006", "quantity": 1, "buyer_agent_id": "buyer-1", "quote_id": quote["quote_id"]},
    )
    assert res.status_code == 200
    assert "payment_link" in res.json()


def test_order_rejects_missing_quote_id(client):
    res = client.post("/api/agent/order", json={"sku_id": "sku-006", "quantity": 1, "buyer_agent_id": "buyer-1"})
    assert res.status_code == 403


def test_order_rejects_invalid_quote_id(client):
    res = client.post(
        "/api/agent/order",
        json={"sku_id": "sku-006", "quantity": 1, "buyer_agent_id": "buyer-1", "quote_id": "qte_does_not_exist"},
    )
    assert res.status_code == 403


def test_order_rejects_expired_quote(client):
    quote = client.post("/api/agent/quote", json={"sku_id": "sku-006", "quantity": 1, "buyer_agent_id": "buyer-1"}).json()

    # Force it into the past rather than sleeping 2 real minutes in a test.
    conn = connect()
    with conn:
        conn.execute("UPDATE quotes SET expires_at = ? WHERE quote_id = ?", (time.time() - 1, quote["quote_id"]))
    conn.close()

    res = client.post(
        "/api/agent/order",
        json={"sku_id": "sku-006", "quantity": 1, "buyer_agent_id": "buyer-1", "quote_id": quote["quote_id"]},
    )
    assert res.status_code == 403


def test_order_rejects_reused_quote(client):
    quote = client.post("/api/agent/quote", json={"sku_id": "sku-006", "quantity": 1, "buyer_agent_id": "buyer-1"}).json()
    body = {"sku_id": "sku-006", "quantity": 1, "buyer_agent_id": "buyer-1", "quote_id": quote["quote_id"]}

    first = client.post("/api/agent/order", json=body)
    assert first.status_code == 200

    second = client.post("/api/agent/order", json=body)
    assert second.status_code == 409


def test_order_rejects_modified_sku(client):
    quote = client.post("/api/agent/quote", json={"sku_id": "sku-006", "quantity": 1, "buyer_agent_id": "buyer-1"}).json()
    res = client.post(
        "/api/agent/order",
        json={"sku_id": "sku-003", "quantity": 1, "buyer_agent_id": "buyer-1", "quote_id": quote["quote_id"]},
    )
    assert res.status_code == 400


def test_order_rejects_modified_quantity(client):
    quote = client.post("/api/agent/quote", json={"sku_id": "sku-006", "quantity": 1, "buyer_agent_id": "buyer-1"}).json()
    res = client.post(
        "/api/agent/order",
        json={"sku_id": "sku-006", "quantity": 2, "buyer_agent_id": "buyer-1", "quote_id": quote["quote_id"]},
    )
    assert res.status_code == 400


def test_order_over_cap_quote_returns_422(client):
    quote = client.post("/api/agent/quote", json={"sku_id": "sku-001", "quantity": 1, "buyer_agent_id": "buyer-1"}).json()
    assert quote["within_auto_approval_bound"] is False

    res = client.post(
        "/api/agent/order",
        json={"sku_id": "sku-001", "quantity": 1, "buyer_agent_id": "buyer-1", "quote_id": quote["quote_id"]},
    )
    assert res.status_code == 422


# --- B/C: webhook signature verification, order mapping, idempotency --------


def test_webhook_valid_signature_marks_order_paid(client):
    order_result = _buy("sku-006")
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
    order_result = _buy("sku-006")
    order_id = order_result["order_id"]
    link_id = order_result["payment_link"]["id"]

    body = json.dumps(webhook_payload(order_id, link_id, "payment_link.paid")).encode()
    res = client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": "not-the-real-signature", "Content-Type": "application/json"},
    )
    assert res.status_code == 400
    assert get_order(order_id)["status"] == "pending"


def test_webhook_duplicate_event_is_safely_ignored(client):
    order_result = _buy("sku-006")
    order_id = order_result["order_id"]
    link_id = order_result["payment_link"]["id"]
    body = json.dumps(webhook_payload(order_id, link_id, "payment_link.paid")).encode()
    headers = {"X-Razorpay-Signature": sign(body), "Content-Type": "application/json"}

    first = client.post("/api/webhooks/razorpay", content=body, headers=headers)
    second = client.post("/api/webhooks/razorpay", content=body, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert get_order(order_id)["status"] == "paid"


def test_webhook_failed_event_marks_order_failed(client):
    order_result = _buy("sku-006")
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
    order_result = _buy("sku-006")
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

    assert get_order(order_id)["status"] == "paid"


# --- D/E: backend-enforced, deterministic upsell flow -----------------------


def test_no_upsell_before_payment():
    result = _buy("sku-003")  # still pending, never paid
    order_id = result["order_id"]

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

    declined = tools_module.run_tool("confirm_upsell", {"order_id": order_id, "accept": False})
    assert declined["status"] == "declined"
    assert "payment_link" not in declined


def test_upsell_accept_creates_separate_order_and_payment_link():
    order_id = _create_and_pay("sku-003")
    offer = tools_module.run_tool("offer_upsell", {"order_id": order_id})["offer"]

    accepted = tools_module.run_tool("confirm_upsell", {"order_id": order_id, "accept": True})
    assert "payment_link" in accepted
    assert accepted["source_order_id"] == order_id
    assert accepted["order_id"] != order_id

    upsell_order = get_order(accepted["order_id"])
    assert upsell_order["kind"] == "upsell"
    assert upsell_order["parent_order_id"] == order_id
    assert upsell_order["sku_id"] == offer["id"]


def test_confirm_upsell_ignores_any_sku_supplied_by_caller():
    order_id = _create_and_pay("sku-003")
    tools_module.run_tool("offer_upsell", {"order_id": order_id})

    result = tools_module.run_tool("confirm_upsell", {"order_id": order_id, "accept": True, "sku_id": "sku-009"})
    upsell_order = get_order(result["order_id"])
    assert upsell_order["sku_id"] != "sku-009"


# --- reconciliation fallback: no webhook received, poll Razorpay directly ---


def test_check_order_status_polls_razorpay_when_no_webhook_received():
    order_id = _buy("sku-006")["order_id"]
    assert get_order(order_id)["status"] == "pending"

    _fake_remote_status["value"] = "paid"
    result = tools_module.run_tool("check_order_status", {"order_id": order_id})

    assert result["status"] == "paid"
    assert get_order(order_id)["status"] == "paid"


def test_check_order_status_leaves_pending_when_remote_is_also_pending():
    order_id = _buy("sku-006")["order_id"]

    _fake_remote_status["value"] = "created"
    result = tools_module.run_tool("check_order_status", {"order_id": order_id})

    assert result["status"] == "pending"
