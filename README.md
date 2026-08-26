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
- [ ] Day 7: Deliberate graceful-failure case
- [ ] Day 8-9: Docker + README polish
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

## What broke / build log

(Keep this section updated as we go — the application form asks for real technical
obstacles, so log them here as they happen instead of reconstructing them later.)

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
