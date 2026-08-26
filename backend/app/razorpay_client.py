import time

import razorpay

from app.config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET, SIMULATE_PAYMENT_FAILURES

_client = None
_simulated_failures_remaining = SIMULATE_PAYMENT_FAILURES


class PaymentLinkError(Exception):
    """Raised when Razorpay payment-link creation fails, including after retries."""


def get_client() -> razorpay.Client:
    global _client
    if _client is None:
        if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
            raise RuntimeError("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set in backend/.env")
        _client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    return _client


def _create_payment_link_once(*, amount_inr: int, description: str, customer_name: str) -> dict:
    global _simulated_failures_remaining
    if _simulated_failures_remaining > 0:
        _simulated_failures_remaining -= 1
        raise PaymentLinkError("Simulated Razorpay outage (SIMULATE_PAYMENT_FAILURES demo flag)")

    client = get_client()
    try:
        link = client.payment_link.create(
            {
                "amount": amount_inr * 100,  # paise
                "currency": "INR",
                "description": description,
                "customer": {"name": customer_name},
                "notify": {"sms": False, "email": False},
                "reminder_enable": False,
            }
        )
    except Exception as e:
        # Covers real Razorpay SDK errors (bad request, server error) and
        # network-layer failures alike — the caller shouldn't need to know
        # which, only that the attempt failed.
        raise PaymentLinkError(str(e)) from e

    return {
        "id": link["id"],
        "short_url": link["short_url"],
        "status": link["status"],
        "amount_inr": amount_inr,
    }


def create_payment_link(
    *, amount_inr: int, description: str, customer_name: str = "AgentCheckout Buyer", max_attempts: int = 2
) -> dict:
    """
    Creates a Razorpay test-mode Payment Link, with one automatic retry on
    failure — real transient errors sometimes clear on a second attempt.
    Raises PaymentLinkError if every attempt fails, so the caller can
    surface a graceful failure instead of a raw 500.
    """
    last_error: PaymentLinkError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            result = _create_payment_link_once(amount_inr=amount_inr, description=description, customer_name=customer_name)
            if attempt > 1:
                result["retried_after_failure"] = True
            return result
        except PaymentLinkError as e:
            last_error = e
            if attempt < max_attempts:
                time.sleep(0.4)
    raise last_error
