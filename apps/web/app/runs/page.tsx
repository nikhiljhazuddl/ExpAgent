import { redirect } from "next/navigation";
import { api } from "@/lib/api";
import { readSession } from "@/lib/session";

export const dynamic = "force-dynamic";

export default async function Runs() {
  const s = readSession();
  if (s.role !== "RevOps" && s.role !== "Admin") redirect("/dashboard");

  const { runs } = await api.runs();
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Runs</h1>
      <table className="w-full text-sm">
        <thead className="text-xs uppercase text-gray-500">
          <tr className="text-left">
            <th className="px-3 py-2">Run ID</th>
            <th className="px-3 py-2">Triggered at</th>
            <th className="px-3 py-2">Triggered</th>
            <th className="px-3 py-2">Survivors</th>
            <th className="px-3 py-2">Kept</th>
            <th className="px-3 py-2">Dry run</th>
          </tr>
        </thead>
        <tbody>
          {runs.length === 0 && (
            <tr>
              <td className="px-3 py-2 text-gray-500" colSpan={6}>
                No runs yet.
              </td>
            </tr>
          )}
          {runs.map((r: any) => (
            <tr key={r.run_id} className="border-t border-white/5">
              <td className="px-3 py-2 font-mono">{r.run_id}</td>
              <td className="px-3 py-2">{r.triggered_at}</td>
              <td className="px-3 py-2">{r.funnel?.triggered}</td>
              <td className="px-3 py-2">{r.funnel?.survivors}</td>
              <td className="px-3 py-2">{r.funnel?.signals_kept ?? "—"}</td>
              <td className="px-3 py-2">{r.dry_run ? "yes" : "no"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
