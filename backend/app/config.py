import os
from dotenv import load_dotenv

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
RAZORPAY_KEY_ID = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.getenv("RAZORPAY_KEY_SECRET", "")

# Guardrail: agent can never create a payment above this without explicit
# human confirmation in the UI (Day 4 guardrail work).
AGENT_MAX_AUTO_AMOUNT_INR = int(os.getenv("AGENT_MAX_AUTO_AMOUNT_INR", "2000"))
