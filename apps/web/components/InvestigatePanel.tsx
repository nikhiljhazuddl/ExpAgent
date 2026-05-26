"use client";

import { useState } from "react";
import type { NotificationDTO } from "@/lib/api";

const RULE_LABEL: Record<string, string> = {
  DQ1_red_adoption: "Adoption health is Red",
  DQ2_recent_activity: "Recently engaged (< 30 days)",
  DQ3_named_open_opp: "Already a named open opportunity",
  DQ4_open_opp_flag: "Open expansion opp in Salesforce",
  DQ5_inactive: "Inactive customer",
};

export function InvestigatePanel({ notification }: { notification: NotificationDTO }) {
  const [open, setOpen] = useState(false);
  const inv = notification.investigate;

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="text-xs underline text-blue-400 hover:text-blue-300"
      >
        Investigate
      </button>
      {open && (
        <div
          className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
          onClick={() => setOpen(false)}
        >
          <div
            className="bg-zinc-950 border border-white/10 rounded-lg max-w-3xl w-full max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="px-6 py-4 border-b border-white/10 sticky top-0 bg-zinc-950 flex justify-between items-center">
              <div>
                <h2 className="text-lg font-bold">{notification.account_name}</h2>
                <div className="text-xs text-gray-500">
                  Why this account was not surfaced this week
                </div>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="text-gray-400 hover:text-white text-2xl leading-none px-2"
                aria-label="Close"
              >
                ×
              </button>
            </div>

            <div className="p-6 space-y-6">
              {/* Top-line explanation */}
              <section className="border border-amber-500/30 bg-amber-500/5 rounded-lg p-4">
                <div className="text-xs uppercase text-amber-300 mb-1">
                  {RULE_LABEL[notification.disqualifier_rule] || notification.disqualifier_rule}
                </div>
                <p className="text-gray-100 leading-relaxed">
                  {inv?.why_disqualified || notification.explanation}
                </p>
              </section>

              {/* What would qualify */}
              {inv?.what_would_qualify && (
                <section>
                  <h3 className="text-sm font-semibold uppercase text-gray-400 mb-2">
                    What would change to re-qualify this account
                  </h3>
                  <p className="text-gray-100">{inv.what_would_qualify}</p>
                </section>
              )}

              {/* Detected gap */}
              <section>
                <h3 className="text-sm font-semibold uppercase text-gray-400 mb-2">
                  Detected expansion opportunity
                </h3>
                <p className="text-gray-100">{notification.detected_gap}</p>
              </section>

              {/* Risk indicators */}
              {(inv?.risk_indicators?.length ?? 0) > 0 && (
                <section>
                  <h3 className="text-sm font-semibold uppercase text-gray-400 mb-2">
                    Signals that reduced ranking
                  </h3>
                  <ul className="list-disc pl-5 text-sm space-y-1.5 text-gray-100">
                    {inv!.risk_indicators.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </section>
              )}

              {/* Factor breakdown */}
              {(inv?.factor_breakdown?.length ?? 0) > 0 && (
                <section>
                  <h3 className="text-sm font-semibold uppercase text-gray-400 mb-2">
                    Factor-by-factor breakdown
                  </h3>
                  <div className="border border-white/10 rounded overflow-hidden">
                    <table className="w-full text-sm">
                      <thead className="bg-white/5">
                        <tr className="text-left text-xs text-gray-500">
                          <th className="px-3 py-2">Factor</th>
                          <th className="px-3 py-2">Value</th>
                          <th className="px-3 py-2">Impact</th>
                        </tr>
                      </thead>
                      <tbody>
                        {inv!.factor_breakdown.map((f, i) => (
                          <tr key={i} className="border-t border-white/5">
                            <td className="px-3 py-2">{f.factor}</td>
                            <td className="px-3 py-2 text-gray-300">{f.value}</td>
                            <td className="px-3 py-2">
                              <Impact tone={f.impact} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              {/* Data quality notes */}
              {(inv?.data_quality_notes?.length ?? 0) > 0 && (
                <section>
                  <h3 className="text-sm font-semibold uppercase text-gray-400 mb-2">
                    Data quality notes
                  </h3>
                  <ul className="text-xs text-gray-400 list-disc pl-5 space-y-1">
                    {inv!.data_quality_notes.map((n, i) => (
                      <li key={i}>{n}</li>
                    ))}
                  </ul>
                </section>
              )}

              {/* Account snapshot */}
              {inv && (
                <section className="grid grid-cols-2 gap-3 text-xs">
                  {inv.adoption_health && (
                    <Snap label="Adoption health" value={inv.adoption_health} />
                  )}
                  {inv.last_activity_days_ago !== undefined && (
                    <Snap
                      label="Last activity"
                      value={
                        inv.last_activity_days_ago === null
                          ? "Unknown"
                          : `${inv.last_activity_days_ago} days ago`
                      }
                    />
                  )}
                  {inv.renewal_proximity_days !== undefined && (
                    <Snap
                      label="Renewal"
                      value={
                        inv.renewal_proximity_days === null
                          ? "Unknown"
                          : `${inv.renewal_proximity_days} days`
                      }
                    />
                  )}
                  <Snap
                    label="Open expansion opp"
                    value={inv.has_open_expansion_opp ? "Yes (in flight)" : "No"}
                  />
                  <Snap
                    label="Customer status"
                    value={inv.is_active_customer ? "Active" : "Inactive"}
                  />
                </section>
              )}

              {/* Footer */}
              <footer className="border-t border-white/10 pt-4 text-xs text-gray-500 flex flex-wrap gap-3 justify-between">
                <div>
                  Account ID:{" "}
                  <span className="font-mono">{notification.account_id}</span>
                </div>
                <div>
                  AE: {notification.ae || "—"} · CSM: {notification.csm || "—"}
                </div>
                <a
                  href={`/accounts/${notification.account_id}`}
                  className="underline hover:text-gray-300"
                >
                  Full account context →
                </a>
              </footer>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function Impact({ tone }: { tone: "positive" | "negative" | "neutral" }) {
  const map = {
    positive: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
    negative: "bg-rose-500/20 text-rose-300 border-rose-500/40",
    neutral: "bg-gray-500/20 text-gray-300 border-gray-500/40",
  } as const;
  const label = { positive: "Helps", negative: "Hurts", neutral: "Neutral" } as const;
  return (
    <span className={`px-2 py-0.5 rounded text-xs border ${map[tone]}`}>{label[tone]}</span>
  );
}

function Snap({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-white/10 rounded p-2">
      <div className="text-gray-500">{label}</div>
      <div className="text-gray-100">{value}</div>
    </div>
  );
}
