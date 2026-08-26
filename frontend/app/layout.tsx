import "./globals.css";

export const metadata = {
  title: "AgentCheckout",
  description: "AI agent that transacts with a merchant on behalf of humans and other agents.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-slate-50 text-slate-900">{children}</body>
    </html>
  );
}
