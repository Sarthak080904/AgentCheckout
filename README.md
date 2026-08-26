# AgentCheckout

Razorpay AI Buildathon 2026 — Track 1: AI Growth & Agentic Commerce.

An AI agent that transacts with a merchant on behalf of a human shopper (chat checkout)
and on behalf of another AI agent (agent-readable catalog + API), on Razorpay test-mode.

## Status: Day 1 scaffold

- [x] Repo structure (`frontend/`, `backend/`)
- [x] Seed catalog (`backend/data/catalog.json`)
- [x] Backend shell (FastAPI) serving `/api/catalog`
- [x] Frontend shell (Next.js) rendering the live catalog
- [x] Day 2-3: Claude tool-calling agent loop + Razorpay test-mode checkout (`/api/chat`)
- [x] Day 4: Guardrails + audit log (`agent_actions` table, `/api/audit-log`)
- [x] Day 5: Agent-readable catalog endpoints (`/api/agent/*`) + buyer-agent simulator (`backend/buyer_agent.py`)
- [x] Day 6: Chat UI (`ChatPanel`) + live audit-log panel (`AuditLogPanel`), polling every 2.5s
- [x] Day 7: Deliberate graceful-failure case (payment-provider retry + graceful apology)
- [ ] Day 8-9: README polish (Docker dropped — see note below)
- [ ] Day 10: 5-min pitch video
- [ ] Day 11: Submit

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

Two ways to transact with the merchant, both going through the same guardrails
and the same audit log:
1. **Human via chat** — `POST /api/chat`, powered by `backend/app/agent.py`
2. **Another AI agent, autonomously** — `backend/buyer_agent.py` is a *separate*
   Claude-powered agent that only knows the `/api/agent/catalog`, `/api/agent/quote`,
   `/api/agent/order` contract (documented at `GET /api/agent/catalog`). It never
   touches our internal code — proving the merchant is actually "sellable to AI
   buyers," not just chat-enabled.

Try it: `python buyer_agent.py "Find me a wireless mouse under 1500 rupees and buy one"`
(needs the backend running on port 8000 first).

## How to verify agent-to-agent commerce

`buyer_agent.py` is a **separate** Claude-powered agent — it does not import or call
any code from `backend/app/`. It only knows the public `/api/agent/*` HTTP contract,
the same way a real external buyer-agent would. This is the actual proof behind the
"transactable by an AI buyer end to end" claim: two independent AI agents (the human
chat agent and this one) both transact with the merchant through the same guardrail
and the same audit log, without sharing a line of code.

**Prerequisites to run it yourself:**
- The backend running locally (`uvicorn app.main:app --port 8000`)
- Your own `ANTHROPIC_API_KEY` in `backend/.env` (this script makes its own Claude
  API calls, separate from the chat agent's)
- Your own Razorpay test-mode keys in `backend/.env` (same ones the rest of the app
  uses — no extra signup beyond what's already needed to run the project at all)

**Steps:**
```bash
# Terminal 1
cd backend
uvicorn app.main:app --port 8000

# Terminal 2 (same venv)
python buyer_agent.py "Find me a wireless mouse under 1500 rupees and buy one"
```

**What to expect:** the terminal prints each step —
`browse_catalog` → `get_quote` → `place_order` — ending with a real Razorpay
test-mode payment link. If the frontend (`localhost:3000`) is open at the same time,
a new row tagged `source: agent-to-agent` appears in the live audit panel within
~2.5s, sitting alongside any `human-chat` rows from the browser chat — same
guardrail, same log, two independent agents.

Try an over-the-cap example too, to see the guardrail refuse it instead of a human
policy check: `python buyer_agent.py "I want 2 mechanical keyboards, buy them for me"`
— the agent should quote the total, recognize it exceeds `AGENT_MAX_AUTO_AMOUNT_INR`,
and decline to place the order on its own.

## Failure recovery (the "one failure handled gracefully")

The guardrail (above) is a *policy* refusal — the agent chose not to act. This is
different: a genuine runtime failure in the Razorpay call itself, caught and
recovered from instead of crashing the request.

`create_payment_link` (`backend/app/razorpay_client.py`) wraps every Razorpay call
with one automatic retry. If the first attempt fails (network blip, transient API
error), it silently retries once before the buyer ever notices. If *both* attempts
fail, `tools.py` catches `PaymentLinkError` and returns a structured
`payment_provider_unavailable` result instead of letting the exception 500 the
request — the agent then apologizes in plain language and offers to try again,
per the rule in `agent.py`'s system prompt.

**To demo this on demand**, set `SIMULATE_PAYMENT_FAILURES` in `backend/.env`
(restart the backend after changing it — it's read once at process start):
- `SIMULATE_PAYMENT_FAILURES=1` — first attempt fails, automatic retry succeeds,
  buyer sees nothing unusual (check `/api/audit-log` — the successful entry has
  `"retried_after_failure": true` in its `result`)
- `SIMULATE_PAYMENT_FAILURES=2` — both attempts fail, the agent apologizes
  ("Sorry, looks like a temporary issue reaching the payment provider... want me
  to try again?") instead of the request crashing; asking it to retry afterward
  succeeds normally since the simulated failures are consumed
- `SIMULATE_PAYMENT_FAILURES=0` (default) — normal operation, no simulated failures

Leave it at `0` outside of demoing this specific behavior.

## Audit trail

Every agent tool call (search, product lookup, payment-link creation — allowed or
blocked) is written to a SQLite database at `backend/data/audit.db`, created
automatically on first run. Schema documented in
[`backend/data/schema.sql`](backend/data/schema.sql); implementation in
[`backend/app/audit.py`](backend/app/audit.py).

To inspect it:
- Live via the API: `GET http://localhost:8000/api/audit-log`
- Directly: `sqlite3 backend/data/audit.db "SELECT * FROM agent_actions ORDER BY id DESC LIMIT 10;"`

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

Visit `http://localhost:3000` — it should show the live catalog fetched from the backend.

**On Docker**: we considered containerizing this (and wrote working Dockerfiles +
a `docker-compose.yml` for it), but the dev machine's virtualization support was
disabled at the hardware/BIOS level, so Docker Desktop couldn't run to verify the
setup — rather than ship an untested Docker config under time pressure, we dropped
it and kept the manual setup above, which has been verified end-to-end multiple
times. A `docker-compose up` version is a reasonable next step if this continues
past the buildathon.

## What broke / build log

(Keep this section updated as we go — the application form asks for real technical
obstacles, so log them here as they happen instead of reconstructing them later.)

- **Day 8-9**: attempted to containerize the app (working Dockerfiles + compose
  written), but Docker Desktop failed to start with "virtualization support not
  detected" — the dev machine's BIOS had Intel VT-x/AMD-V disabled. Rather than
  burn remaining time chasing a hardware setting or shipping unverified Docker
  config this close to the deadline, made the call to drop Docker entirely and
  rely on the manual setup, which is fully tested. A real scoping tradeoff under
  time pressure, not a shortcut taken lightly.
- **Day 1**: `pip install` initially hit the global Python environment and conflicted
  with unrelated packages (litellm, mcp). Fixed by giving the backend its own `.venv`.
- **Day 2-3**: pinning `anthropic==0.34.2` broke against the installed `httpx` version
  (`Client.__init__() got an unexpected keyword argument 'proxies'`) — the SDK's
  internal httpx client construction changed across versions. Fixed by upgrading to
  `anthropic>=1.0.0`. Also hit an Anthropic account credit-balance error on the first
  real API call — not a code bug, just needed billing credits added.
- **Day 5**: `buyer_agent.py` crashed on its final summary print with
  `UnicodeEncodeError: 'charmap' codec can't encode character '₹'` — Windows'
  default console codepage (cp1252) can't render the ₹ sign our tool results
  contain. Fixed by forcing UTF-8 on stdout at the top of the script.
- **Day 6**: React hydration error in `ChatPanel` —
  `Error: Text content does not match server-rendered HTML`. Cause:
  `useState(() => crypto.randomUUID())` ran once during Next.js's server-side
  render and again during client hydration, producing two different UUIDs.
  Fixed by initializing `sessionId` as `""` and generating the real UUID inside
  a `useEffect` (client-only, runs after hydration).
- **Day 6**: sending a chat message (Enter or Send click) scrolled the whole
  page down, not just the chat panel. Two contributing bugs: (1) the
  auto-scroll-to-latest-message logic used `scrollIntoView()` on a marker div,
  which scrolls *every* scrollable ancestor into view including the page
  itself — fixed by setting `scrollTop` directly on the chat's own message
  container instead; (2) `disabled={loading}` was applied to the input/button
  while they held focus — disabling a focused element forces a browser blur,
  which was also moving the scroll position. Fixed by removing `disabled` and
  guarding double-submits with a ref instead.
- **Day 6**: the Razorpay payment link in the chat reply wasn't clickable —
  replies are rendered as plain strings, so the URL was just text. Fixed with
  a small `renderWithLinks()` helper that detects `http(s)` URLs and wraps
  them in real `<a target="_blank">` tags.
