const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Product = {
  id: string;
  name: string;
  category: string;
  price_inr: number;
  description: string;
  stock: number;
};

async function getCatalog(): Promise<Product[]> {
  try {
    const res = await fetch(`${API_URL}/api/catalog`, { cache: "no-store" });
    if (!res.ok) return [];
    return res.json();
  } catch {
    // Backend not running yet — Day 1 just proves the wiring exists.
    return [];
  }
}

export default async function Home() {
  const products = await getCatalog();

  return (
    <main className="max-w-3xl mx-auto p-8">
      <h1 className="text-2xl font-semibold mb-1">AgentCheckout</h1>
      <p className="text-slate-500 mb-6">
        Track 1 — AI Growth &amp; Agentic Commerce. Day 1 scaffold: frontend fetching live catalog from backend.
      </p>

      {products.length === 0 ? (
        <div className="rounded border border-amber-300 bg-amber-50 p-4 text-amber-800 text-sm">
          No products loaded. Start the backend (<code>uvicorn app.main:app --reload</code> in{" "}
          <code>backend/</code>) and refresh.
        </div>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2">
          {products.map((p) => (
            <li key={p.id} className="rounded border border-slate-200 bg-white p-4">
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
