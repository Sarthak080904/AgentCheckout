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
- [ ] Day 5: Agent-readable catalog endpoints + buyer-agent simulator script
- [ ] Day 6: Chat UI + live agent-reasoning panel
- [ ] Day 7: Deliberate graceful-failure case
- [ ] Day 8-9: Docker + README polish
- [ ] Day 10: 5-min pitch video
- [ ] Day 11: Submit

## Architecture

```
frontend (Next.js)  <-->  backend (FastAPI)  <-->  Razorpay test-mode APIs
                              |
                              +--> catalog.json / DB
                              +--> agent_actions audit log (Day 4)
                              +--> /api/agent/* (Day 5, consumed by a second AI agent)
```

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
