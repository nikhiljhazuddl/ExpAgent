import { redirect } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { readSession } from "@/lib/session";
import { PriorityBadge } from "@/components/PriorityBadge";

export const dynamic = "force-dynamic";

const DQ_LABEL: Record<string, string> = {
  DQ1_red_adoption: "Adoption Red",
  DQ2_recent_activity: "Recently engaged",
  DQ3_named_open_opp: "Named open opp",
  DQ4_open_opp_flag: "Open opp flag",
  DQ5_inactive: "Inactive",
};

export default async function Executive() {
  const session = readSession();
  if (!session.user || !session.role) redirect("/login");
  if (session.role !== "RevOps" && session.role !== "Admin") redirect("/dashboard");

  const [summary, signalsRes, notifsRes] = await Promise.all([
    api.runsLatest().catch(() => null),
    api.signals(session.role).catch(() => ({ signals: [] as any[] })),
    api.notifications().catch(() => ({ notifications: [] as any[] })),
  ]);
  const signals = (signalsRes as any).signals as any[];
  const notifications = (notifsRes as any).notifications as any[];

  // Aggregates
  const bandDist = { high: 0, medium: 0, low: 0 } as Record<string, number>;
  const byOwner = { AE: 0, CSM: 0, BOTH: 0 } as Record<string, number>;
  const byUseCase: Record<string, number> = {};
  const byAE: Record<string, number> = {};
  const byCSM: Record<string, number> = {};
  let confidenceSum = 0;
  let confidenceCount = 0;
  let scoreSum = 0;
  let scoreCount = 0;
  const churnAccounts: any[] = [];

  for (const s of signals) {
    bandDist[s.priority_band || "low"] = (bandDist[s.priority_band || "low"] || 0) + 1;
    byOwner[s.recommended_action_owner || "AE"] =
      (byOwner[s.recommended_action_owner || "AE"] || 0) + 1;
    if (s.missing_use_case) byUseCase[s.missing_use_case] = (byUseCase[s.missing_use_case] || 0) + 1;
    const ae = s.ownership?.ae?.name;
    const csm = s.ownership?.csm?.name;
    if (ae) byAE[ae] = (byAE[ae] || 0) + 1;
    if (csm) byCSM[csm] = (byCSM[csm] || 0) + 1;
    if (typeof s.confidence === "number") {
      confidenceSum += s.confidence;
      confidenceCount++;
    }
    if (typeof s.final_score === "number") {
      scoreSum += s.final_score;
      scoreCount++;
    }
    if ((s.ontology_grounding?.churn_indicators_present?.length || 0) > 0) {
      churnAccounts.push(s);
    }
  }

  const dqBreakdown: Record<string, number> = {};
  for (const n of notifications) {
    dqBreakdown[n.disqualifier_rule] = (dqBreakdown[n.disqualifier_rule] || 0) + 1;
  }

  const totalSurvivors = summary?.funnel?.survivors || 0;
  const winRate = totalSurvivors ? (signals.length / totalSurvivors) * 100 : 0;

  return (
    <div className="space-y-8">
      <header className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-3xl font-bold">Executive overview</h1>
          <p className="text-sm text-gray-400 mt-1">
            Organization-wide picture of the expansion pipeline · {summary?.run_id}
          </p>
        </div>
        <Link
          href="/dashboard"
          className="text-sm text-gray-400 underline hover:text-gray-200"
        >
          ← Back to operational view
        </Link>
      </header>

      {/* Top-line KPIs */}
      <section className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi
          label="Accounts in scope"
          value={summary?.funnel?.total || 0}
          sub={`${summary?.funnel?.triggered || 0} triggered`}
        />
        <Kpi
          label="Survived to AI scoring"
          value={summary?.funnel?.survivors || 0}
          sub={`${summary?.funnel?.disqualified || 0} disqualified`}
        />
        <Kpi
          label="Signals delivered"
          value={signals.length}
          sub={`${winRate.toFixed(0)}% of survivors`}
        />
        <Kpi
          label="Avg confidence"
          value={
            confidenceCount ? (confidenceSum / confidenceCount).toFixed(2) : "—"
          }
          sub={`Avg final score ${scoreCount ? (scoreSum / scoreCount).toFixed(2) : "—"}`}
        />
      </section>

      {/* Priority distribution */}
      <section className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <h2 className="text-sm font-semibold uppercase text-gray-400 mb-3">
            Priority distribution
          </h2>
          <div className="space-y-2">
            {(["high", "medium", "low"] as const).map((band) => {
              const count = bandDist[band] || 0;
              const pct = signals.length ? (count / signals.length) * 100 : 0;
              return (
                <Row
                  key={band}
                  left={<PriorityBadge band={band} />}
                  pct={pct}
                  right={`${count}`}
                />
              );
            })}
          </div>
        </div>

        <div>
          <h2 className="text-sm font-semibold uppercase text-gray-400 mb-3">
            Recommended action owner
          </h2>
          <div className="space-y-2">
            {(["AE", "CSM", "BOTH"] as const).map((owner) => {
              const count = byOwner[owner] || 0;
              const pct = signals.length ? (count / signals.length) * 100 : 0;
              return (
                <Row
                  key={owner}
                  left={<span className="font-semibold text-sm">{owner}</span>}
                  pct={pct}
                  right={`${count}`}
                />
              );
            })}
          </div>
        </div>
      </section>

      {/* Expansion mix */}
      <section>
        <h2 className="text-sm font-semibold uppercase text-gray-400 mb-3">
          Expansion opportunity mix
        </h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {Object.entries(byUseCase)
            .sort((a, b) => b[1] - a[1])
            .map(([uc, n]) => (
              <div key={uc} className="border border-white/10 rounded p-3">
                <div className="text-xs text-gray-500 uppercase">{uc}</div>
                <div className="text-2xl font-bold">{n}</div>
              </div>
            ))}
        </div>
      </section>

      {/* Team breakdown */}
      <section className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div>
          <h2 className="text-sm font-semibold uppercase text-gray-400 mb-3">
            Signals per AE
          </h2>
          <div className="space-y-2">
            {Object.entries(byAE)
              .sort((a, b) => b[1] - a[1])
              .map(([name, n]) => (
                <Row
                  key={name}
                  left={<span className="text-sm">{name}</span>}
                  pct={signals.length ? (n / signals.length) * 100 : 0}
                  right={`${n}`}
                />
              ))}
          </div>
        </div>
        <div>
          <h2 className="text-sm font-semibold uppercase text-gray-400 mb-3">
            Signals per CSM
          </h2>
          <div className="space-y-2">
            {Object.entries(byCSM)
              .sort((a, b) => b[1] - a[1])
              .map(([name, n]) => (
                <Row
                  key={name}
                  left={<span className="text-sm">{name}</span>}
                  pct={signals.length ? (n / signals.length) * 100 : 0}
                  right={`${n}`}
                />
              ))}
          </div>
        </div>
      </section>

      {/* Disqualifier breakdown */}
      <section>
        <h2 className="text-sm font-semibold uppercase text-gray-400 mb-3">
          Why accounts were dropped
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {Object.entries(dqBreakdown)
            .sort((a, b) => b[1] - a[1])
            .map(([rule, n]) => (
              <Row
                key={rule}
                left={<span className="text-sm">{DQ_LABEL[rule] || rule}</span>}
                pct={notifications.length ? (n / notifications.length) * 100 : 0}
                right={`${n}`}
              />
            ))}
        </div>
      </section>

      {/* Churn risk surface */}
      {churnAccounts.length > 0 && (
        <section className="border border-rose-500/30 bg-rose-500/5 rounded-lg p-4">
          <h2 className="text-sm font-semibold uppercase text-rose-200 mb-3">
            ⚠️ Churn indicators present on expansion candidates
          </h2>
          <p className="text-xs text-gray-400 mb-3">
            These accounts are surfacing expansion but the agent also flagged churn signals.
            Worth a manual review.
          </p>
          <ul className="text-sm space-y-1.5">
            {churnAccounts.map((s) => (
              <li key={s.id} className="flex justify-between border-b border-rose-500/20 pb-1">
                <Link href={`/signal/${encodeURIComponent(s.id)}`} className="text-rose-100 hover:underline">
                  {s.account_name}
                </Link>
                <span className="text-xs text-gray-500">
                  {s.ownership?.ae?.name} · {s.ownership?.csm?.name}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <p className="text-xs text-gray-500">
        V2 will add trend charts (weekly priority movement, account-health timelines,
        funnel velocity) once multiple runs accumulate. Today's view is a single-run
        snapshot.
      </p>
    </div>
  );
}

function Kpi({ label, value, sub }: { label: string; value: any; sub?: string }) {
  return (
    <div className="border border-white/10 rounded p-3">
      <div className="text-xs uppercase text-gray-500">{label}</div>
      <div className="text-3xl font-bold">{value}</div>
      {sub && <div className="text-xs text-gray-400 mt-1">{sub}</div>}
    </div>
  );
}

function Row({
  left,
  pct,
  right,
}: {
  left: React.ReactNode;
  pct: number;
  right: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-3 text-sm">
      <div className="w-32 shrink-0">{left}</div>
      <div className="flex-1 bg-white/5 rounded h-2 overflow-hidden">
        <div
          className="bg-emerald-400/60 h-full"
          style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
        />
      </div>
      <div className="w-12 text-right text-gray-300">{right}</div>
    </div>
  );
}
