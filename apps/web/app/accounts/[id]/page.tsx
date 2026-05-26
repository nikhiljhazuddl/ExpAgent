import { api } from "@/lib/api";
import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

export default async function AccountDetail({ params }: { params: { id: string } }) {
  const ctx = await api.account(decodeURIComponent(params.id)).catch(() => null);
  if (!ctx) notFound();
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">{ctx.account_name}</h1>
      <p className="text-xs text-gray-500">{ctx.account_id} · {ctx.domain}</p>
      <pre className="text-xs whitespace-pre-wrap bg-black/40 border border-white/10 rounded p-4 overflow-auto">
        {JSON.stringify(ctx, null, 2)}
      </pre>
    </div>
  );
}
