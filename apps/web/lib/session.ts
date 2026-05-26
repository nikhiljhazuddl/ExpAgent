import { cookies } from "next/headers";

export type Session = { role: string | null; user: string | null };

export function readSession(): Session {
  const raw = cookies().get("session")?.value;
  if (!raw) return { role: null, user: null };
  const parts: Record<string, string> = {};
  for (const chunk of raw.split("&")) {
    const [k, v] = chunk.split("=");
    if (k && v !== undefined) parts[k] = decodeURIComponent(v);
  }
  return { role: parts.role || null, user: parts.user || null };
}
