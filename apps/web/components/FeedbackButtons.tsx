"use client";

import { useState } from "react";

export function FeedbackButtons({ signalId, runId }: { signalId: string; runId?: string }) {
  const [status, setStatus] = useState<string | null>(null);

  async function submit(relevant: boolean | null, actioned: boolean | null) {
    setStatus("Saving…");
    const res = await fetch("/api/feedback", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ signal_id: signalId, run_id: runId, relevant, actioned }),
    });
    setStatus(res.ok ? "Saved." : "Failed.");
    setTimeout(() => setStatus(null), 2000);
  }

  return (
    <div className="flex gap-2 items-center">
      <button
        onClick={() => submit(true, null)}
        className="px-3 py-1.5 rounded bg-emerald-500/20 border border-emerald-500/40 hover:bg-emerald-500/30 text-sm"
      >
        Mark Relevant
      </button>
      <button
        onClick={() => submit(false, null)}
        className="px-3 py-1.5 rounded bg-rose-500/20 border border-rose-500/40 hover:bg-rose-500/30 text-sm"
      >
        Not Relevant
      </button>
      <button
        onClick={() => submit(null, true)}
        className="px-3 py-1.5 rounded bg-blue-500/20 border border-blue-500/40 hover:bg-blue-500/30 text-sm"
      >
        Mark Actioned
      </button>
      {status && <span className="text-xs text-gray-400 ml-2">{status}</span>}
    </div>
  );
}
