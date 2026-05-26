import "./globals.css";
import Link from "next/link";
import { readSession } from "@/lib/session";

export const metadata = {
  title: "GTM Mesh — Expansion Agent",
  description: "Zuddl Revenue Agentic System",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  const session = readSession();
  return (
    <html lang="en">
      <body>
        <header className="border-b border-white/10 px-6 py-4 flex items-center gap-6">
          <Link href="/dashboard" className="font-bold">
            GTM Mesh
          </Link>
          <nav className="flex gap-4 text-sm text-gray-400">
            <Link href="/dashboard">Dashboard</Link>
            {(session.role === "RevOps" || session.role === "Admin") && (
              <Link href="/executive">Executive</Link>
            )}
            <Link href="/notifications">Notifications</Link>
            {(session.role === "RevOps" || session.role === "Admin") && (
              <Link href="/runs">Runs</Link>
            )}
          </nav>
          <div className="ml-auto text-sm text-gray-400">
            {session.user ? (
              <span>
                {session.user} <span className="text-gray-500">({session.role})</span> ·{" "}
                <Link href="/login" className="underline">
                  switch
                </Link>
              </span>
            ) : (
              <Link href="/login" className="underline">
                login
              </Link>
            )}
          </div>
        </header>
        <main className="px-6 py-8 max-w-[1400px] mx-auto">{children}</main>
      </body>
    </html>
  );
}
