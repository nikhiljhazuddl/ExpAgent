export function PriorityBadge({ band }: { band?: string }) {
  const map: Record<string, string> = {
    high: "bg-pink-500/20 text-pink-300 border-pink-500/40",
    medium: "bg-amber-500/20 text-amber-300 border-amber-500/40",
    low: "bg-gray-500/20 text-gray-300 border-gray-500/40",
  };
  const cls = map[band || "low"];
  return (
    <span className={`px-2 py-0.5 rounded text-xs border ${cls}`}>
      {(band || "low").toUpperCase()}
    </span>
  );
}
