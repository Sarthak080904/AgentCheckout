import AgentWorkspace from "./components/AgentWorkspace";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Product = {
  id: string;
  name: string;
  category: string;
  price_inr: number;
  description: string;
  stock: number;
  image_url?: string;
};

async function getCatalog(): Promise<Product[]> {
  try {
    const res = await fetch(`${API_URL}/api/catalog`, { cache: "no-store" });
    if (!res.ok) return [];
    return res.json();
  } catch {
    return [];
  }
}

export default async function Home() {
  const products = await getCatalog();

  return (
    <main className="mx-auto max-w-6xl p-8">
      <h1 className="mb-1 text-2xl font-semibold">AgentCheckout</h1>
      <p className="mb-6 text-slate-500">
        Track 1 — AI Growth &amp; Agentic Commerce. Chat with the shopping agent on the left;
        every action it takes — allowed or blocked by the guardrail — shows up live on the right.
      </p>

      <AgentWorkspace />

      <h2 className="mb-3 mt-10 text-lg font-medium">Storefront (reference)</h2>
      {products.length === 0 ? (
        <div className="rounded border border-amber-300 bg-amber-50 p-4 text-sm text-amber-800">
          No products loaded. Start the backend (<code>uvicorn app.main:app --reload</code> in{" "}
          <code>backend/</code>) and refresh.
        </div>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {products.map((p) => (
            <li key={p.id} className="rounded border border-slate-200 bg-white p-4">
              {p.image_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={p.image_url} alt={p.name} className="mb-3 h-40 w-full rounded object-cover" />
              )}
              <div className="font-medium">{p.name}</div>
              <div className="text-sm text-slate-500">{p.description}</div>
              <div className="mt-2 text-sm">
                ₹{p.price_inr} · {p.stock} in stock
              </div>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
