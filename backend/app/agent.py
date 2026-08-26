from anthropic import Anthropic

from app.config import ANTHROPIC_API_KEY, AGENT_MAX_AUTO_AMOUNT_INR
from app.tools import TOOL_SCHEMAS, run_tool
from app.audit import log_action

MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = f"""You are the shopping assistant for an online merchant on Razorpay.
Help the buyer find products from the catalog and complete checkout.

Rules:
- Always search the catalog before recommending a product; never invent products or prices.
- When multiple variants match (e.g. different colors), show the buyer the options.
- Before calling create_payment_link, explicitly restate the product, quantity, and total
  price, and get the buyer's clear confirmation in the conversation first.
- create_payment_link will refuse orders above Rs {AGENT_MAX_AUTO_AMOUNT_INR} (a hard safety
  cap). If that happens, tell the buyer plainly that this order needs manual/human approval
  and cannot be auto-completed by you.
- After creating a payment link, tell the buyer to click it to complete payment in
  Razorpay's test-mode checkout.
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
            result = run_tool(block.name, block.input)
            actions.append({"tool": block.name, "input": block.input, "result": result, "reasoning": reasoning})

            if block.name == "create_payment_link":
                within_bound = result.get("within_bound", True)
                outcome = "created" if "payment_link" in result else ("blocked_over_limit" if not within_bound else "error")
                log_action(
                    session_id=session_id,
                    tool=block.name,
                    tool_input=block.input,
                    result=result,
                    amount_inr=result.get("amount_inr"),
                    bound_limit_inr=AGENT_MAX_AUTO_AMOUNT_INR,
                    within_bound=within_bound,
                    outcome=outcome,
                )
            else:
                log_action(
                    session_id=session_id,
                    tool=block.name,
                    tool_input=block.input,
                    result=result,
                    amount_inr=None,
                    bound_limit_inr=None,
                    within_bound=True,
                    outcome="info",
                )

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
