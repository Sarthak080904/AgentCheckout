import razorpay

from app.config import RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET

_client = None


def get_client() -> razorpay.Client:
    global _client
    if _client is None:
        if not RAZORPAY_KEY_ID or not RAZORPAY_KEY_SECRET:
            raise RuntimeError("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set in backend/.env")
        _client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    return _client


def create_payment_link(*, amount_inr: int, description: str, customer_name: str = "AgentCheckout Buyer") -> dict:
    """Creates a Razorpay test-mode Payment Link. amount_inr is in whole rupees."""
    client = get_client()
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
    return {
        "id": link["id"],
        "short_url": link["short_url"],
        "status": link["status"],
        "amount_inr": amount_inr,
    }
