# AgentCheckout

Razorpay AI Buildathon 2026 — Track 1: AI Growth & Agentic Commerce.

An AI agent that transacts with a merchant on behalf of a human shopper (chat checkout)
and on behalf of another AI agent (agent-readable catalog + API), on Razorpay test-mode.

## Architecture

```
frontend (Next.js)  <-->  backend (FastAPI)  <-->  Razorpay test-mode APIs
                              |         ^
                              |         |
                              |    buyer_agent.py (independent AI agent,
                              |    talks ONLY to /api/agent/*, no shared code)
                              |
                              +--> catalog.json
                              +--> agent_actions audit log (source: human-chat | agent-to-agent)
```

Two ways to transact with the merchant, both going through the same guardrails and
the same audit log:
1. **Human via chat** — `POST /api/chat`, powered by `backend/app/agent.py`
2. **Another AI agent, autonomously** — `backend/buyer_agent.py` is a separate
   Claude-powered agent that only knows the `/api/agent/catalog`, `/api/agent/quote`,
   `/api/agent/order` HTTP contract. It never touches our internal code — proving the
   merchant is actually sellable to AI buyers, not just chat-enabled.

The chat agent also grows revenue directly, but only after a purchase is actually
paid for — see [Payment confirmation & upsell flow](#payment-confirmation--upsell-flow)
below for how that's enforced in backend code, not just prompted.

## Run locally

Backend:
```bash
cd backend
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
cp ../.env.example .env   # fill in ANTHROPIC_API_KEY, RAZORPAY_KEY_ID/SECRET, RAZORPAY_WEBHOOK_SECRET
uvicorn app.main:app --reload --port 8000
```

Frontend:
```bash
cd frontend
npm install
npm run dev
```

Visit `http://localhost:3000`.

## Verifying agent-to-agent commerce

```bash
# backend running first (above), then in another terminal, same venv:
python buyer_agent.py "Find me a wireless mouse under 1500 rupees and buy one"
```

Prints `browse_catalog` → `get_quote` → `place_order`, ending with a real Razorpay
payment link. With the frontend open, a `source: agent-to-agent` row lands in the
live audit panel at the same time, next to any `human-chat` rows — same guardrail,
same log, two independent agents.

To see the guardrail refuse instead: `python buyer_agent.py "I want 2 mechanical
keyboards, buy them for me"` — exceeds `AGENT_MAX_AUTO_AMOUNT_INR`, agent declines on
its own.

## Purchase confirmation gate (human chat)

Nothing in the system prompt can *prove* a buyer actually approved a purchase — a
model slip could call `create_payment_link` without one. So confirmation is a backend
state machine, not a prompt instruction:

1. `request_purchase_confirmation(sku_id, quantity)` — computes the real amount from
   the catalog (never trusts a number the model says) and stores a `pending_confirmations`
   row, `status='requested'`.
2. `confirm_purchase(sku_id, quantity, confirmed)` — must reference the exact sku_id/
   quantity that was requested, or it's rejected as a mismatch. Transitions the row to
   `confirmed` or `rejected`.
3. `create_payment_link(sku_id, quantity)` — refuses to run unless there's a `confirmed`
   row for that session whose sku_id/quantity match *exactly*. On success it atomically
   consumes the row (`status='consumed'`) — **single-use**: the same confirmation can
   never authorize a second payment link, and a different product/quantity always needs
   a fresh `request_purchase_confirmation`.

Rejected requests, mapped to what actually happens:
- No confirmation at all → `create_payment_link` returns `confirmation_required`
- Confirmed sku-A, qty 1, then tried to buy sku-B or qty 2 → `confirmation_mismatch`
- Reusing an already-consumed confirmation → `confirmation_already_consumed`
- Buyer said no → `confirm_purchase` returns `status: "rejected"`, no link is ever created

This is why `agent.py`'s system prompt never claims a purchase is approved on its own
authority — it only ever *reports* what `confirm_purchase`/`create_payment_link`
actually returned.

## Agent-to-agent quote gate

The equivalent protection for `buyer_agent.py`/any external buyer agent, since prompts
don't apply there at all — this is pure HTTP contract enforcement:

1. `POST /api/agent/quote` snapshots `sku_id`/`quantity`/`amount_inr`/cap-status
   server-side and returns a `quote_id`, valid for **2 minutes**.
2. `POST /api/agent/order` requires that exact `quote_id` and rejects:
   - missing `quote_id` → `403`
   - unknown `quote_id` → `403`
   - expired `quote_id` → `403`
   - already-consumed `quote_id` (reused) → `409`
   - `sku_id`/`quantity` that don't match what was quoted → `400`
   - quote reports over the auto-approval cap → `422`
3. On success, the quote is marked consumed — a valid quote authorizes exactly one order.

A buyer agent can ask for whatever quote it wants, but it cannot talk its way into an
order that doesn't match the server's own numbers.

**Example rejected requests** (run against a local backend on port 8000):
```bash
# Missing quote_id -> 403
curl -X POST http://localhost:8000/api/agent/order \
  -H "Content-Type: application/json" \
  -d '{"sku_id": "sku-006", "quantity": 1, "buyer_agent_id": "test"}'

# Reusing a quote_id from an order that already succeeded -> 409
curl -X POST http://localhost:8000/api/agent/order \
  -H "Content-Type: application/json" \
  -d '{"sku_id": "sku-006", "quantity": 1, "buyer_agent_id": "test", "quote_id": "qte_already_used"}'

# Quoted quantity 1, order tries quantity 2 -> 400 (quote_mismatch)
curl -X POST http://localhost:8000/api/agent/order \
  -H "Content-Type: application/json" \
  -d '{"sku_id": "sku-006", "quantity": 2, "buyer_agent_id": "test", "quote_id": "<a real qty-1 quote_id>"}'

# Zero quantity -> 400 (invalid_quantity)
curl -X POST http://localhost:8000/api/agent/quote \
  -H "Content-Type: application/json" \
  -d '{"sku_id": "sku-006", "quantity": 0}'
```

## Payment confirmation & upsell flow

**A payment link being created does not mean the customer paid.** It only means a
`pending` order was recorded (`backend/app/orders.py`, `orders` table). The order only
becomes `paid` when Razorpay's webhook confirms it — nothing else marks it paid, and
the upsell logic is gated on that status in backend code, not just prompted in the
system prompt.

Flow:
1. Customer confirms a product (via the gate above) → `create_payment_link` validates
   quantity/stock/cap, creates the Razorpay link with the local `order_id` embedded in
   its `notes`, and inserts a `pending` order.
2. Customer pays via the Razorpay-hosted checkout page.
3. Razorpay calls `POST /api/webhooks/razorpay` with a signed event. The endpoint
   verifies the signature (HMAC-SHA256 over the raw body, using
   `RAZORPAY_WEBHOOK_SECRET`), rejects anything that doesn't match, reads `order_id`
   back out of the notes, and marks that order `paid` (or `failed` on
   expiry/cancellation). Duplicate or out-of-order events are safely ignored — a
   `failed` event can never downgrade an already-`paid` order.
4. **No public URL for the webhook?** `check_order_status` also polls Razorpay
   directly for the payment link's real status if the order is still `pending`
   locally — so without ngrok/a tunnel set up, asking the agent "have I paid?"
   still correctly reconciles a real completed payment instead of staying stuck
   on `pending` forever. The webhook remains the primary, production-correct
   path; this is strictly a local-dev fallback (`reconcile_payment_status` in
   the audit log, distinguishable from webhook-driven `original_payment_completed`
   entries via its `reason` field).
5. Only once the order is `paid` (via either path above) does the agent call
   `offer_upsell(order_id)` — a plain Python function (`orders.select_upsell`, no LLM
   call) that deterministically picks one product that's in stock, in a different
   category, not the same SKU, and ≤ ₹1,000 (preferring a thematically related
   category, falling back to cheapest). This offer is stored in `pending_upsells`.
6. The buyer's explicit yes/no goes through `confirm_upsell(order_id, accept)` — note
   there's no `sku_id` field in that tool's schema at all, so the model has no way to
   substitute a different product; it can only accept or decline the exact one already
   stored. Accepting creates a genuinely separate order (`kind='upsell'`,
   `parent_order_id` pointing at the original) and a separate Razorpay payment link.

**Configuring the webhook**: in the Razorpay dashboard, Settings → Webhooks → add
`http://<your-host>/api/webhooks/razorpay`, subscribe to at least `payment_link.paid`
and `payment_link.expired`/`payment_link.cancelled`, and copy the webhook secret it
gives you into `RAZORPAY_WEBHOOK_SECRET` in `backend/.env`.

**Testing the webhook locally** (Razorpay can't reach `localhost` directly):
- Use a tunnel (e.g. `ngrok http 8000`) and point the dashboard webhook at the
  `https://*.ngrok.io/api/webhooks/razorpay` URL it gives you, or
- Simulate it directly without any real payment or tunnel — sign a fake payload
  yourself and POST it:
  ```bash
  python -c "
  import hmac, hashlib, json
  secret = 'your_webhook_secret_here'
  body = json.dumps({
      'event': 'payment_link.paid',
      'payload': {'payment_link': {'entity': {'id': 'plink_test', 'notes': {'order_id': 'ord_...'}}}}
  }).encode()
  sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
  print(body.decode()); print(sig)
  "
  # then: curl -X POST http://localhost:8000/api/webhooks/razorpay \
  #   -H "X-Razorpay-Signature: <sig>" -H "Content-Type: application/json" -d '<body>'
  ```
  (substitute a real `order_id` from a payment link you just created via the chat or
  `/api/agent/order`)

The audit log (below) records every step of every flow on this page —
`purchase_confirmation_requested`, `purchase_confirmed`, `purchase_rejected`,
`quote_created`, `quote_missing`/`quote_invalid`/`quote_expired`/`quote_reused`/
`quote_mismatch`, `blocked_over_limit`, `created`, `original_payment_completed`,
`original_payment_failed`, `upsell_offered`, `upsell_declined`,
`upsell_payment_created`, `invalid_webhook`, `duplicate_webhook_ignored` — each tagged
with `order_id`/`sku_id`/a human-readable `reason` where relevant, visible in the
frontend's live panel too.

## Failure recovery

`razorpay_client.create_payment_link()` retries once automatically on failure. If both
attempts fail, `tools.py` returns a structured error instead of crashing the request,
and the agent apologizes and offers to retry (per `agent.py`'s system prompt) — a real
runtime failure handled gracefully, distinct from the guardrail's policy refusal.

Demo on demand via `SIMULATE_PAYMENT_FAILURES` in `backend/.env` (restart backend
after changing): `1` = silent retry succeeds, `2` = both attempts fail and the agent
apologizes, `0` (default) = normal operation.

## Audit trail

Every tool call — search, lookup, payment-link creation (allowed or blocked) — is
logged to SQLite (`backend/data/audit.db`, schema in `backend/data/schema.sql`),
auto-created on first run.

**To see it without running the frontend** (backend only, `uvicorn app.main:app --port 8000`):
- Paste `http://localhost:8000/api/audit-log` into a browser — raw JSON of every logged action
- Or open `http://localhost:8000/docs`, expand `GET /api/audit-log`, click "Try it out" —
  FastAPI's built-in interactive UI, no extra code from us
- Or, without even the backend running: `sqlite3 backend/data/audit.db "SELECT * FROM agent_actions ORDER BY id DESC LIMIT 10;"`

**Why SQLite and not Supabase for this.** I considered Supabase early on, since it's
Postgres-as-a-service and would've given me a hosted DB with zero server ops. But the
audit log only needs one thing: a single backend process appending rows and reading
them back. There's no second service writing to it, no multi-user access, no need for
real-time sync across clients — so a hosted, networked Postgres instance would be
solving a problem I don't have here.

What it would cost me: anyone running this repo — a judge included — would first need
to create their own Supabase project and paste in credentials before the app even
starts, or I'd have to ship my own project's credentials in the repo, which isn't
something I'm willing to do. SQLite is just a file. It's created automatically the
first time the backend runs, no signup, no network call, no `.env` value to chase down
just to see the audit trail. For a judge cloning this cold, that's the difference
between "clone and run" and "clone, sign up somewhere, configure, then run."

If this were going into production with multiple services or people hitting the
audit log concurrently, I'd revisit this — that's a real limitation of SQLite I'm
aware of, not something I'm pretending isn't there. But for what this component
actually needs to do inside an 11-day build, it was the right call.

## What broke / build log

- `pip install` initially hit the global Python environment and conflicted with
  unrelated packages. Fixed by giving the backend its own `.venv`.
- Pinning `anthropic==0.34.2` broke against the installed `httpx` version
  (`Client.__init__() got an unexpected keyword argument 'proxies'`). Fixed by
  upgrading to `anthropic>=1.0.0`.
- `buyer_agent.py` crashed on its summary print with `UnicodeEncodeError` — Windows'
  default console codepage can't render the ₹ sign. Fixed by forcing UTF-8 stdout.
- React hydration error in `ChatPanel`: `useState(() => crypto.randomUUID())` ran
  once during SSR and again on client hydration, producing two different UUIDs.
  Fixed by generating the UUID inside a `useEffect` instead.
- Sending a chat message scrolled the whole page, not just the chat panel. Two
  causes: `scrollIntoView()` on the auto-scroll marker scrolls every scrollable
  ancestor including the page (fixed via direct `scrollTop` on the chat's own
  container); `disabled={loading}` on a focused input forces a browser blur that
  also moved scroll position (fixed by guarding double-submits with a ref instead).
- Payment links in chat replies weren't clickable — replies are plain strings.
  Fixed with a `renderWithLinks()` helper that wraps URLs in real `<a>` tags.
- Attempted to containerize with Docker; Docker Desktop failed to start
  ("virtualization support not detected" — disabled at the BIOS level on the dev
  machine). Dropped Docker rather than ship an unverified config under time
  pressure; the manual setup above is fully tested.
- After adding the upsell nudge, the agent sometimes dropped the payment link
  from its reply entirely when it also did the upsell search in the same turn
  (e.g. buy a mouse → link created → agent checks for a mouse pad, finds none →
  final reply only said "skipping the add-on," never mentioning the link that
  was actually created). The system prompt's upsell instruction was competing
  with "always mention the link" and winning. Fixed by making the payment-link
  mention explicitly non-negotiable regardless of what else happens in the same
  turn, and telling the model to skip a failed upsell search silently instead of
  narrating it.
- The model sometimes wrapped a payment link in markdown bold (`**url**`). Since
  the chat renders plain text, the literal `**` characters got swept into the URL
  match itself, corrupting the actual link (e.g. `...crzn**` — a broken slug that
  led to an empty/error page). Fixed both ends: told the system prompt to never
  use markdown (plain text only, bare URLs), and hardened `renderWithLinks()` to
  strip trailing markdown/punctuation from the `href` even if the model slips up
  again, while still showing that trailing text so nothing visually disappears.
- Moving upsell selection into backend code (`orders.select_upsell`) surfaced a bug
  the prompt-only version never would have: the affinity map's `"electronics":
  ["electronics", "bags"]` preferred the *same* category first, which the candidate
  filter always excludes anyway — a dead, never-reachable preference. Only found it
  because a test (`test_upsell_is_different_category_and_not_same_sku`) exercises the
  actual selection function directly. Fixed the affinity map.
- After adding the backend confirmation gate, the first live test showed the agent
  asking the buyer to confirm *twice* — once informally ("want this one?"), then
  again after calling `request_purchase_confirmation` in a later turn ("Confirm:
  X, qty 1, total Rs Y?"). Not a correctness bug (the gate still held), but a real
  UX regression — an extra round-trip the buyer shouldn't need. Cause: the prompt
  said to call the tool "as soon as the buyer has picked a product," which the
  model interpreted as *after* an initial informal ask rather than *instead of* one.
  Fixed by making the instruction explicit: call `request_purchase_confirmation`
  before saying anything, and use its returned amount as the one and only
  confirmation question. Verified live — collapsed back to a single confirmation
  round-trip.
- The same live test then surfaced a real bug: `create_payment_link` consumed the
  buyer's confirmation *before* attempting the Razorpay call, so when a genuine
  transient Razorpay failure hit, the confirmation was already burned — the buyer
  would've had to reconfirm from scratch even though nothing was actually created.
  Fixed by only consuming the confirmation after `create_order_and_link` actually
  succeeds; on failure it's restored to `confirmed` so the same confirmation can
  be retried. Added a regression test
  (`test_confirmation_survives_a_failed_payment_link_attempt`).
- While retesting that fix live, hit two real Razorpay failures in a row —
  diagnosed directly against the API and found the actual cause: Razorpay's
  test-mode account has a hard cap ("test mode limit of 30 reached for
  payment_link"), exhausted by testing throughout the build. Not a code bug —
  flagging here since it'll affect anyone recording a demo after heavy testing;
  check the Razorpay dashboard for clearing old test links, or whether the
  account's limit resets on a schedule, before recording.
- With the quota exhausted, live-testing the upsell flow surfaced the exact same
  class of bug in a second place: `confirm_upsell` also marked the pending
  upsell "accepted" unconditionally, even when the Razorpay call for its
  payment link failed. Same fix as the purchase-confirmation gate — only mark
  it accepted once a link is actually created; on failure it stays "offered" so
  accepting again can retry without re-rolling a new upsell. Added
  `test_upsell_offer_survives_a_failed_payment_link_attempt` (38 tests now).

## Tests

`backend/tests/test_backend.py` — 38 tests. Run with:
```bash
cd backend
pytest
```
(needs the venv's dependencies installed, including `pytest`).

Covers, roughly in this order:
- **Human-chat confirmation gate**: rejected with no confirmation, allowed once
  confirmed, a confirmation for one SKU/quantity can't authorize a different one,
  single-use (consumed after one payment link), declined confirmations block the
  purchase, confirmations are scoped per session.
- **Quantity/amount validation**: zero/negative quantity, over-stock, over-cap (and
  that it's logged), and that the mocked Razorpay function is never even called for
  an invalid request.
- **Agent-to-agent quote gate**: a valid quote allows ordering; missing, unknown,
  expired, reused, and sku/quantity-modified quotes are all rejected with the
  documented status codes.
- **Webhook**: valid signature marks an order paid, invalid signature is rejected
  (and doesn't touch the order), duplicate events are safely ignored, a
  failed/expired event can't downgrade an already-paid order.
- **Upsell flow**: no offer before payment, offer only after payment, offer is a
  different category/SKU and ≤ ₹1,000, explicit accept/decline required, `confirm_upsell`
  can't be steered to a different SKU by the caller.
- **Payment-status reconciliation** (no webhook received): polls Razorpay directly.

`create_payment_link` is monkeypatched in every test — no real Razorpay calls happen
during the test run.