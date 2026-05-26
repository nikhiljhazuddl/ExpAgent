"use client";

import { useState } from "react";
import { BulletList } from "./BulletList";
import type { ExplanationBullet } from "@/lib/api";

type Section = {
  id: string;
  icon: string;
  label: string;
  bullets?: ExplanationBullet[] | string[] | string;
  prose?: string;
  tone?: "default" | "emerald" | "blue" | "amber";
  badge?: string; // optional counter shown next to label
};

type Props = {
  sections: Section[];
  technical?: React.ReactNode; // optional last tab for the technical-details collapse
};

const TONE_RING: Record<NonNullable<Section["tone"]>, string> = {
  default: "border-white/15",
  emerald: "border-emerald-500/40",
  blue: "border-blue-500/40",
  amber: "border-amber-500/40",
};

const TONE_TEXT: Record<NonNullable<Section["tone"]>, string> = {
  default: "text-gray-300",
  emerald: "text-emerald-300",
  blue: "text-blue-300",
  amber: "text-amber-300",
};

export function InsightTabs({ sections, technical }: Props) {
  const visible = sections.filter((s) => {
    if (s.bullets) {
      if (Array.isArray(s.bullets)) return s.bullets.length > 0;
      if (typeof s.bullets === "string") return s.bullets.trim().length > 0;
    }
    if (s.prose && s.prose.trim().length > 0) return true;
    return false;
  });

  const [activeId, setActiveId] = useState<string>(
    visible[0]?.id ?? (technical ? "__tech" : ""),
  );

  const active = visible.find((s) => s.id === activeId);
  const showTech = activeId === "__tech";

  return (
    <div className="border border-white/10 rounded-lg overflow-hidden flex flex-col bg-zinc-950">
      {/* Tab strip */}
      <div
        role="tablist"
        className="flex flex-col border-b border-white/10 bg-zinc-900/50 max-h-[280px] overflow-y-auto"
      >
        {visible.map((s) => {
          const isActive = s.id === activeId;
          const tone = s.tone ?? "default";
          return (
            <button
              key={s.id}
              role="tab"
              aria-selected={isActive}
              onClick={() => setActiveId(s.id)}
              className={`flex items-center gap-2 px-4 py-2.5 text-left text-sm border-l-2 transition ${
                isActive
                  ? `${TONE_RING[tone]} bg-white/5`
                  : "border-transparent hover:bg-white/5"
              }`}
            >
              <span className="text-base">{s.icon}</span>
              <span
                className={`flex-1 ${isActive ? TONE_TEXT[tone] : "text-gray-300"}`}
              >
                {s.label}
              </span>
              {s.badge && (
                <span className="text-[10px] text-gray-500 font-mono">
                  {s.badge}
                </span>
              )}
            </button>
          );
        })}
        {technical && (
          <button
            role="tab"
            aria-selected={showTech}
            onClick={() => setActiveId("__tech")}
            className={`flex items-center gap-2 px-4 py-2.5 text-left text-sm border-l-2 transition border-t border-white/5 ${
              showTech ? "border-l-white/40 bg-white/5" : "border-transparent hover:bg-white/5"
            }`}
          >
            <span className="text-base">🔧</span>
            <span className="flex-1 text-gray-300">Technical details</span>
          </button>
        )}
      </div>

      {/* Content panel */}
      <div className="p-5 flex-1 min-h-[200px] max-h-[640px] overflow-y-auto">
        {showTech ? (
          technical
        ) : active ? (
          <>
            <div
              className={`text-xs uppercase mb-3 flex items-center gap-2 ${
                TONE_TEXT[active.tone ?? "default"]
              }`}
            >
              <span className="text-base">{active.icon}</span>
              <span>{active.label}</span>
            </div>
            {active.prose ? (
              <p className="text-gray-100 leading-relaxed text-sm">{active.prose}</p>
            ) : (
              <BulletList items={active.bullets as any} />
            )}
          </>
        ) : (
          <p className="text-sm text-gray-500">No insights available.</p>
        )}
      </div>
    </div>
  );
}
