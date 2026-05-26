import { redirect } from "next/navigation";
import { api } from "@/lib/api";
import { readSession } from "@/lib/session";
import { InvestigatePanel } from "@/components/InvestigatePanel";

export const dynamic = "force-dynamic";

const RULE_LABEL: Record<string, string> = {
  DQ1_red_adoption: "Adoption Red",
  DQ2_recent_activity: "Recently engaged",
  DQ3_named_open_opp: "Named open opp",
  DQ4_open_opp_flag: "Open opp flag",
  DQ5_inactive: "Inactive",
};

export default async function Notifications() {
  const session = readSession();
  if (!session.user || !session.role) redirect("/login");

  const { notifications } =
    session.role === "RevOps" || session.role === "Admin"
      ? await api.notifications()
      : await api.notifications(session.role, session.user);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Transparency log</h1>
      <p className="text-sm text-gray-400">
        Accounts where the system detected an expansion gap but dropped them from
        this week's queue. Click <strong>Investigate</strong> for the full reasoning
        — factor-by-factor.
      </p>
      <div className="border border-white/10 rounded overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-white/5 text-left text-xs uppercase text-gray-500">
            <tr>
              <th className="px-4 py-2">Account</th>
              <th className="px-4 py-2">Gap detected</th>
              <th className="px-4 py-2">Reason dropped</th>
              <th className="px-4 py-2">Plain-English explanation</th>
              <th className="px-4 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {notifications.length === 0 && (
              <tr>
                <td className="px-4 py-3 text-gray-500" colSpan={5}>
                  No accounts dropped from this week's queue.
                </td>
              </tr>
            )}
            {notifications.map((n, i) => (
              <tr key={`${n.account_id}-${i}`} className="border-t border-white/5 align-top">
                <td className="px-4 py-2">{n.account_name}</td>
                <td className="px-4 py-2 text-gray-300">{n.detected_gap}</td>
                <td className="px-4 py-2">
                  <span className="text-xs border border-white/20 rounded px-1.5 py-0.5">
                    {RULE_LABEL[n.disqualifier_rule] || n.disqualifier_rule}
                  </span>
                </td>
                <td className="px-4 py-2 text-gray-400 max-w-md">{n.explanation}</td>
                <td className="px-4 py-2 whitespace-nowrap">
                  <InvestigatePanel notification={n} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
