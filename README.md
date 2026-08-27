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

The chat agent also grows revenue directly: right after a purchase completes, it
searches for one complementary, modestly-priced product in a different category
(e.g. socks with running shoes) and offers it as a single optional add-on — accepting
it is treated as its own confirmed order, never silently bundled into the first
payment link.

## Run locally

Backend:
```bash
cd backend
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
cp ../.env.example .env   # fill in ANTHROPIC_API_KEY, RAZORPAY_KEY_ID/SECRET
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