import "./globals.css";

export const metadata = {
  title: "AgentCheckout",
  description: "AI agent that transacts with a merchant on behalf of humans and other agents.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gradient-to-b from-slate-50 to-slate-100 text-slate-900 antialiased">
        {children}
      </body>
    </html>
  );
}
