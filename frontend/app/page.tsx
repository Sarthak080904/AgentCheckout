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
      <div className="mb-8 flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary text-lg font-semibold text-primary-foreground">
          A
        </div>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-foreground">AgentCheckout</h1>
          <span className="inline-block rounded-full bg-secondary/30 px-2 py-0.5 text-xs font-medium text-foreground/70">
            Track 1 — AI Growth &amp; Agentic Commerce
          </span>
        </div>
      </div>
      <p className="mb-6 max-w-3xl text-muted-foreground">
        Chat with the shopping agent on the left; every action it takes — allowed or blocked
        by the guardrail — shows up live on the right.
      </p>

      <AgentWorkspace />

      <h2 className="mb-3 mt-10 text-lg font-medium text-foreground">Storefront (reference)</h2>
      {products.length === 0 ? (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-4 text-sm text-amber-800">
          No products loaded. Start the backend (<code>uvicorn app.main:app --reload</code> in{" "}
          <code>backend/</code>) and refresh.
        </div>
      ) : (
        <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {products.map((p) => (
            <li
              key={p.id}
              className="group overflow-hidden rounded-xl border border-border bg-card shadow-sm transition hover:-translate-y-0.5 hover:shadow-md"
            >
              {p.image_url && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={p.image_url}
                  alt={p.name}
                  className="h-40 w-full object-cover transition group-hover:scale-105"
                />
              )}
              <div className="p-4">
                <div className="font-medium text-card-foreground">{p.name}</div>
                <div className="mt-1 text-sm text-muted-foreground">{p.description}</div>
                <div className="mt-3 flex items-center justify-between">
                  <span className="font-semibold text-card-foreground">₹{p.price_inr}</span>
                  <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
                    {p.stock} in stock
                  </span>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </main>
  );
}
