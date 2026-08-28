import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
# Secret configured for the Razorpay webhook endpoint.
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

# Maximum amount an agent may auto-approve.
AGENT_MAX_AUTO_AMOUNT_INR = int(os.getenv("AGENT_MAX_AUTO_AMOUNT_INR", "2000"))

# Test aid: force this many payment-link attempts to fail before normal calls.
SIMULATE_PAYMENT_FAILURES = int(os.getenv("SIMULATE_PAYMENT_FAILURES", "0"))
