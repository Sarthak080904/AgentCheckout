# AgentCheckout

AI-powered commerce for humans and AI buyers, built for Razorpay Test Mode.

AgentCheckout helps a shopper discover products, confirm a purchase, and receive a Razorpay payment link. It also exposes a machine-readable catalog and quote-gated order API for independent buyer agents.

The core promise is simple: every money action is bounded, gated, explainable, and auditable.

## Highlights

- Human checkout through an AI shopping assistant.
- Independent agent-to-agent commerce through `/api/agent/*`.
- Server-enforced purchase confirmation for chat orders.
- Short-lived, single-use quote tokens for external buyer agents.
- Razorpay Payment Links with retry and graceful failure handling.
- Signed payment webhooks and payment-status reconciliation.
- Deterministic post-payment upsells with separate confirmation and payment links.
- Live SQLite audit trail for approvals, payments, blocks, failures, and upsells.

## Architecture

```text
Next.js frontend
        │
        ▼
FastAPI backend ─── Razorpay Test Mode
        │
        ├── catalog.json + local product images
        ├── SQLite orders, quotes, confirmations, and audit events
        └── buyer_agent.py → /api/agent/*
```

## Run locally

### Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
```

Create `backend/.env` from `.env.example` and set:

```env
ANTHROPIC_API_KEY=...
RAZORPAY_KEY_ID=...
RAZORPAY_KEY_SECRET=...
RAZORPAY_WEBHOOK_SECRET=...
AGENT_MAX_AUTO_AMOUNT_INR=2000
SIMULATE_PAYMENT_FAILURES=0
```

Start the API:

```bash
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Demo flows

### Human checkout

Use the chat interface to find a product. The backend requires this sequence:

```text
catalog search → confirmation request → explicit confirmation → payment link
```

The confirmation is matched to the exact SKU and quantity, then consumed after successful payment-link creation.

### Agent-to-agent checkout

With the backend running:

```bash
cd backend
python buyer_agent.py "Find me a wireless mouse under 1500 rupees and buy one"
```

The independent buyer agent uses only:

```text
browse catalog → request quote → place order with the same quote_id
```

Quotes expire after two minutes, are single-use, and cannot be modified. An order above the auto-approval cap is rejected before Razorpay is called:

```bash
python buyer_agent.py "I want 2 mechanical keyboards, buy them for me"
```

### Payment confirmation and upsell

Creating a payment link creates a `pending` order; it does not mean payment succeeded. The order becomes `paid` after a verified Razorpay webhook or status reconciliation.

Only after payment is confirmed does the backend select one complementary add-on. The add-on must be in stock, from a different category, different from the original SKU, and priced at or below ₹1,000. Accepting it creates a separate order and payment link.

## Razorpay webhooks

Configure a Razorpay Test Mode webhook at:

```text
POST /api/webhooks/razorpay
```

Subscribe to:

```text
payment_link.paid
payment_link.expired
payment_link.cancelled
```

For local testing, Razorpay needs a public URL. Use a tunnel such as:

```bash
ngrok http 8000
```

Then configure the generated HTTPS URL plus `/api/webhooks/razorpay` in the Razorpay Dashboard. The webhook secret belongs in `RAZORPAY_WEBHOOK_SECRET`; it is separate from the Razorpay API secret.

Without a tunnel, `check_order_status` can reconcile the payment directly with Razorpay. Signed local webhook payload testing is covered by automated tests.

## API surface

| Endpoint | Purpose |
|---|---|
| `GET /api/catalog` | Human-facing catalog |
| `POST /api/chat` | AI shopping assistant |
| `GET /api/agent/catalog` | Machine-readable catalog and contract |
| `POST /api/agent/quote` | Create a server-side quote |
| `POST /api/agent/order` | Place a quote-authorized order |
| `POST /api/webhooks/razorpay` | Verify payment-link events |
| `GET /api/audit-log` | View audit events |
| `GET /health` | Health check |

Interactive API documentation is available at [http://localhost:8000/docs](http://localhost:8000/docs).

## Testing

```bash
cd backend
pytest -q
python -m compileall -q .
```

The test suite covers confirmation and quote gates, quantity/stock/cap validation, webhook signatures and idempotency, payment reconciliation, deterministic upsells, failure recovery, and audit logging. Razorpay calls are mocked in tests.

Build the frontend with:

```bash
cd frontend
npm run build
```

## Project layout

```text
backend/app/                 FastAPI routes, agent tools, orders, quotes, webhooks
backend/data/catalog.json    Product catalog
backend/data/product-images/ Local catalog images
backend/tests/               Backend test suite
backend/buyer_agent.py       Independent AI buyer client
frontend/app/                Next.js UI and live audit panel
```

## Limitations

- Razorpay live webhook delivery requires ngrok or another public HTTPS URL during local development.
- The project demonstrates payment-link creation and payment confirmation; fulfillment, shipping, refunds, and production inventory reservation are outside the demo scope.
- SQLite is suitable for this single-process demo, but a production multi-service deployment should use a managed database.
