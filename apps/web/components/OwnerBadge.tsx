export function OwnerBadge({ owner }: { owner?: string }) {
  const map: Record<string, string> = {
    AE: "bg-blue-500/20 text-blue-300 border-blue-500/40",
    CSM: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
    BOTH: "bg-purple-500/20 text-purple-300 border-purple-500/40",
  };
  const cls = map[owner || "AE"] || map.AE;
  return (
    <span className={`px-2 py-0.5 rounded text-xs border ${cls}`}>
      {owner || "—"}
    </span>
  );
}
