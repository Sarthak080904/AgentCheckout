from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.catalog import load_catalog, find_product
from app.agent import run_agent_turn

app = FastAPI(title="AgentCheckout API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/catalog")
def get_catalog():
    return load_catalog()


@app.get("/api/catalog/{sku_id}")
def get_product(sku_id: str):
    product = find_product(sku_id)
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return product


class ChatRequest(BaseModel):
    history: list[dict]  # full prior conversation, e.g. [{"role": "user", "content": "..."}]


@app.post("/api/chat")
def chat(req: ChatRequest):
    try:
        result = run_agent_turn(req.history)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"reply": result["reply"], "messages": result["messages"], "actions": result["actions"]}


# --- Day 5: agent-readable endpoints for a second AI agent (buyer-agent) ---
@app.get("/api/agent/catalog")
def agent_catalog():
    raise HTTPException(status_code=501, detail="Agent-readable catalog not implemented yet (Day 5)")
