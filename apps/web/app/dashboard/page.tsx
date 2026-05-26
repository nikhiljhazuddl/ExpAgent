import { redirect } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { readSession } from "@/lib/session";
import { SignalCard } from "@/components/SignalCard";
import { ExtrasReveal } from "@/components/ExtrasReveal";

export const dynamic = "force-dynamic";

export default async function Dashboard() {
  const session = readSession();
  if (!session.user || !session.role) redirect("/login");

  if (session.role === "RevOps" || session.role === "Admin") {
    const [summary, signalsRes] = await Promise.all([
      api.runsLatest().catch(() => null),
      api.signals(session.role).catch(() => ({ signals: [] as any[] })),
    ]);
    return (
      <div className="space-y-8">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h1 className="text-2xl font-bold">Revenue overview</h1>
          <Link
            href="/executive"
            className="text-sm border border-emerald-500/30 bg-emerald-500/10 hover:bg-emerald-500/20 rounded px-3 py-1.5 text-emerald-200"
          >
            Executive dashboard →
          </Link>
        </div>
        {summary && (
          <section>
            <h2 className="font-semibold mb-3">Latest run · {summary.run_id}</h2>
            <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
              {Object.entries(summary.funnel).map(([k, v]) => (
                <div key={k} className="border border-white/10 rounded p-3">
                  <div className="text-xs uppercase text-gray-500">
                    {k.replace(/_/g, " ")}
                  </div>
                  <div className="text-2xl font-bold">{v}</div>
                </div>
              ))}
            </div>
          </section>
        )}
        <section>
          <h2 className="font-semibold mb-3">
            All expansion signals ({(signalsRes as any).signals.length})
          </h2>
          {(signalsRes as any).signals.length === 0 ? (
            <p className="text-sm text-gray-500">
              No signals yet. Run <code>make agent-run</code> with an API key set.
            </p>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {(signalsRes as any).signals.map((s: any) => (
                <SignalCard key={s.id} signal={s} />
              ))}
            </div>
          )}
        </section>
      </div>
    );
  }

  // AE / CSM
  const { signals, extras } = await api.signals(session.role, session.user);

  return (
    <div className="space-y-8">
      <header>
        <h1 className="text-2xl font-bold">
          Welcome, {session.user}{" "}
          <span className="text-gray-500 text-base">({session.role})</span>
        </h1>
        <p className="text-sm text-gray-400 mt-1">
          Your top expansion opportunities for the week.{" "}
          <Link href="/notifications" className="underline">
            See dropped accounts and why →
          </Link>
        </p>
      </header>

      {/* Section 1 — Top 5 in a responsive grid */}
      <section>
        <h2 className="text-sm font-semibold uppercase text-gray-400 mb-3">
          Top {signals.length} accounts this week
        </h2>
        {signals.length === 0 ? (
          <p className="text-sm text-gray-500">
            No active signals in your queue right now. (After a full run populates them,
            you'll see up to 5 here.)
          </p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {signals.map((s) => (
              <SignalCard key={s.id} signal={s} />
            ))}
          </div>
        )}
      </section>

      {/* Section 2 — Expandable ranks 6-10 */}
      {extras && extras.length > 0 && <ExtrasReveal extras={extras} />}

      {/* Section 3 — Disqualified link */}
      <section className="border border-amber-500/20 bg-amber-500/5 rounded-lg p-4">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <div className="text-sm font-semibold text-amber-200">
              Accounts we dropped this week
            </div>
            <div className="text-xs text-gray-400 mt-1">
              The system detected expansion gaps on other accounts in your book but
              dropped them for transparency-logged reasons (recent activity, open opps,
              adoption health, etc.).
            </div>
          </div>
          <Link
            href="/notifications"
            className="text-sm border border-amber-500/30 hover:bg-amber-500/10 rounded px-3 py-1.5 text-amber-200"
          >
            View transparency log →
          </Link>
        </div>
      </section>
    </div>
  );
}
