import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")
# Set in the Razorpay dashboard (Settings -> Webhooks) when creating the
# webhook pointed at /api/webhooks/razorpay; used to verify that inbound
# webhook calls actually came from Razorpay.
RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

# Guardrail: agent can never create a payment above this without explicit
# human confirmation in the UI (Day 4 guardrail work).
AGENT_MAX_AUTO_AMOUNT_INR = int(os.getenv("AGENT_MAX_AUTO_AMOUNT_INR", "2000"))

# Demo/test aid (Day 7): forces this many Razorpay payment-link calls to fail
# before letting the real call through. Set to 1 to see the automatic retry
# succeed silently; set to 2+ (>= the retry count in razorpay_client.py) to
# see every retry exhausted and the agent fail gracefully instead. Leave at 0
# for normal operation — this never affects real traffic unless set.
SIMULATE_PAYMENT_FAILURES = int(os.getenv("SIMULATE_PAYMENT_FAILURES", "0"))
