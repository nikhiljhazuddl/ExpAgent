"use client";

import { useState } from "react";
import type { Signal } from "@/lib/api";
import { SignalCard } from "./SignalCard";

export function ExtrasReveal({ extras }: { extras: Signal[] }) {
  const [open, setOpen] = useState(false);
  if (!extras || extras.length === 0) return null;

  return (
    <section>
      {!open ? (
        <button
          onClick={() => setOpen(true)}
          className="w-full border border-dashed border-white/20 rounded-lg p-4 hover:bg-white/5 text-sm text-gray-300"
        >
          Would you like to see {extras.length} more accounts? (ranks{" "}
          {6}–{5 + extras.length})
        </button>
      ) : (
        <>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold uppercase text-gray-400">
              Ranks {6}–{5 + extras.length} · secondary opportunities
            </h2>
            <button
              onClick={() => setOpen(false)}
              className="text-xs text-gray-500 hover:underline"
            >
              Collapse
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {extras.map((s) => (
              <SignalCard key={s.id} signal={s} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}
