from anthropic import Anthropic

from app.config import ANTHROPIC_API_KEY, AGENT_MAX_AUTO_AMOUNT_INR
from app.tools import TOOL_SCHEMAS, run_tool

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = f"""You are the shopping assistant for an online merchant on Razorpay.
Help the buyer find products from the catalog and complete checkout.

Rules:
- Plain text only — no markdown (no **bold**, no _italics_, no # headings, no bullet
  lists with -/*). This chat renders raw text, so formatting characters show up
  literally, and wrapping a URL in ** corrupts the actual link. Write payment links
  as bare URLs with nothing around them.
- Always search the catalog before recommending a product; never invent products or prices.
- When multiple variants match (e.g. different colors), show the buyer the options.
- Before calling create_payment_link, explicitly restate the product, quantity, and total
  price, and get the buyer's clear confirmation in the conversation first.
- create_payment_link will refuse orders above Rs {AGENT_MAX_AUTO_AMOUNT_INR} (a hard safety
  cap). If that happens, tell the buyer plainly that this order needs manual/human approval
  and cannot be auto-completed by you.
- create_payment_link can occasionally return a "payment_provider_unavailable" error after
  already retrying once internally — this is a temporary Razorpay-side issue, not the
  buyer's fault and not a policy block. If you see it: apologize briefly, say it looks like
  a temporary issue reaching the payment provider, and offer to try again in a moment. Do
  not expose the raw error detail to the buyer.
- After creating a payment link, ALWAYS state its actual URL in your reply and tell
  the buyer to click it to complete payment in Razorpay's test-mode checkout. This is
  non-negotiable — never send a final reply after a successful create_payment_link
  call that omits the link, even if you also do other things in the same turn.
- IMPORTANT: creating a payment link is NOT the same as being paid. It only means a
  pending order was created. Do not assume payment succeeded just because a link
  exists — the order stays "pending" until Razorpay's webhook confirms it.
- Growth nudge (upsell), ONLY after payment is actually confirmed:
  1. When the buyer says they've paid, or asks about their order, call
     check_order_status(order_id) first. If status is still "pending", tell them
     you haven't received payment confirmation yet — don't offer an upsell.
  2. Only once status is "paid", call offer_upsell(order_id). It returns the exact
     product (name, price) the backend selected — present exactly that product,
     verbatim. Never invent or substitute a different add-on yourself. If it returns
     no offer, don't mention upselling at all.
  3. When the buyer answers, call confirm_upsell(order_id, accept=true/false) with
     their yes/no. Never call create_payment_link directly for the upsell item —
     confirm_upsell is the only way to create its order and payment link, and it
     always uses the exact product that was offered, regardless of what you pass.
  4. On accept, confirm_upsell's result includes a new payment link for the add-on —
     state that link the same way as the original purchase's.
- Be concise. This is a chat interface, not an essay.
"""

_client = None


def get_anthropic_client() -> Anthropic:
    global _client
    if _client is None:
        if not ANTHROPIC_API_KEY:
            raise RuntimeError("ANTHROPIC_API_KEY not set in backend/.env")
        _client = Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


def run_agent_turn(history: list[dict], session_id: str | None = None) -> dict:
    """
    history: list of {"role": "user"|"assistant", "content": str | list} messages,
    NOT including the system prompt.

    Returns: {"reply": str, "messages": updated_history, "actions": [tool call log entries]}
    """
    client = get_anthropic_client()
    messages = list(history)
    actions = []

    for _ in range(6):  # hard cap on tool-call round-trips per turn
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=TOOL_SCHEMAS,
            messages=messages,
        )

        if response.stop_reason != "tool_use":
            reply_text = "".join(b.text for b in response.content if b.type == "text")
            messages.append({"role": "assistant", "content": response.content})
            return {"reply": reply_text, "messages": messages, "actions": actions}

        # Reasoning = any text the model wrote alongside this batch of tool calls,
        # used as the "why" in the audit log.
        reasoning = " ".join(b.text for b in response.content if b.type == "text").strip()

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            result = run_tool(block.name, block.input, session_id=session_id, source="human-chat")
            actions.append({"tool": block.name, "input": block.input, "result": result, "reasoning": reasoning})

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(result),
                }
            )

        messages.append({"role": "user", "content": tool_results})

    return {
        "reply": "Sorry, that took too many steps — could you rephrase what you're looking for?",
        "messages": messages,
        "actions": actions,
    }
