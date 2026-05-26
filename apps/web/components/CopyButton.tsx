"use client";

import { useState } from "react";

export function CopyButton({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
      className="px-2 py-1 text-xs rounded bg-white/10 hover:bg-white/20 border border-white/20"
    >
      {done ? "Copied!" : "Copy"}
    </button>
  );
}
