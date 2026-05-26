import type { ExplanationBullet } from "@/lib/api";

type BulletsInput = ExplanationBullet[] | string[] | string | undefined | null;

function normalize(input: BulletsInput): ExplanationBullet[] {
  if (!input) return [];
  if (typeof input === "string") {
    // legacy prose — render as a single bullet with no source
    return [{ text: input, source: "" }];
  }
  return (input as any[]).map((b) =>
    typeof b === "string" ? { text: b, source: "" } : b,
  );
}

export function BulletList({ items }: { items: BulletsInput }) {
  const bullets = normalize(items);
  if (bullets.length === 0) return null;
  return (
    <ul className="space-y-2 text-sm">
      {bullets.map((b, i) => (
        <li key={i} className="flex gap-2">
          <span className="text-gray-500 select-none mt-0.5">•</span>
          <div className="min-w-0 flex-1">
            <span className="text-gray-100 leading-snug">{b.text}</span>
            {b.source && (
              <span className="ml-2 text-[10px] text-gray-500 italic whitespace-nowrap">
                ← {b.source}
              </span>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
