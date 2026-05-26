import Link from "next/link";
import type { Signal } from "@/lib/api";
import { PriorityBadge } from "./PriorityBadge";
import { OwnerBadge } from "./OwnerBadge";

export function SignalCard({ signal }: { signal: Signal }) {
  // Dashboard teaser: build from the first ~2 bullets of explanation_why_prioritized,
  // or fall back to why_now / legacy prose.
  const why = signal.explanation_why_prioritized;
  let teaser = signal.why_now || "";
  if (Array.isArray(why)) {
    teaser = (why as any[])
      .slice(0, 2)
      .map((b) => (typeof b === "string" ? b : b.text))
      .join(" · ");
  } else if (typeof why === "string") {
    teaser = why;
  }
  const persona = signal.who_to_target?.primary;

  return (
    <Link
      href={`/signal/${encodeURIComponent(signal.id)}`}
      className="block border border-white/10 hover:border-white/30 rounded-lg p-4 transition bg-zinc-950/40"
    >
      {/* Top row: account + badges */}
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="min-w-0">
          <h3 className="font-semibold text-base truncate">{signal.account_name}</h3>
          <div className="text-xs text-gray-500 mt-0.5">
            Missing:{" "}
            <span className="text-gray-300">{signal.missing_use_case || "—"}</span>
          </div>
        </div>
        <div className="flex gap-1.5 shrink-0">
          <PriorityBadge band={signal.priority_band} />
          <OwnerBadge owner={signal.recommended_action_owner} />
        </div>
      </div>

      {/* Narrative teaser — clamped to 3 lines so cards stay aligned */}
      <p className="text-sm text-gray-300 leading-snug line-clamp-3 mb-3">
        {teaser}
      </p>

      {/* Persona pill */}
      {persona && (
        <div className="text-xs border border-emerald-500/20 bg-emerald-500/5 rounded px-2 py-1.5 mb-2">
          <span className="text-gray-500">Target: </span>
          <span className="text-gray-100 font-medium">{persona.name}</span>
          <span className="text-gray-500"> · {persona.title}</span>
        </div>
      )}

      {/* Footer meta strip */}
      <div className="flex items-center justify-between gap-2 text-[11px] text-gray-500 pt-2 border-t border-white/5">
        <div className="flex gap-3">
          <span>
            Score{" "}
            <span className="text-gray-200 font-mono">
              {signal.final_score?.toFixed(2) ?? "—"}
            </span>
          </span>
          <span>
            Conf{" "}
            <span className="text-gray-200 font-mono">
              {signal.confidence?.toFixed(2) ?? "—"}
            </span>
          </span>
        </div>
        <div className="truncate text-right">
          AE {signal.ownership?.ae?.name || "?"} · CSM{" "}
          {signal.ownership?.csm?.name || "?"}
        </div>
      </div>
    </Link>
  );
}
