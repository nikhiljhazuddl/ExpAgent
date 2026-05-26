import { notFound } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";
import { PriorityBadge } from "@/components/PriorityBadge";
import { OwnerBadge } from "@/components/OwnerBadge";
import { FeedbackButtons } from "@/components/FeedbackButtons";
import { CopyButton } from "@/components/CopyButton";
import { TechnicalDetails } from "@/components/TechnicalDetails";
import { InsightTabs } from "@/components/InsightTabs";

export const dynamic = "force-dynamic";

function count(bullets: any): string | undefined {
  if (!bullets) return undefined;
  if (Array.isArray(bullets)) return bullets.length ? String(bullets.length) : undefined;
  return undefined;
}

export default async function SignalDetail({ params }: { params: { id: string } }) {
  const id = decodeURIComponent(params.id);
  const s = await api.signal(id).catch(() => null);
  if (!s) notFound();
  const runId = id.includes(":") ? id.split(":")[0] : undefined;

  const sections = [
    {
      id: "why",
      icon: "⭐",
      label: "Why prioritized",
      bullets: s.explanation_why_prioritized as any,
      tone: "emerald" as const,
      badge: count(s.explanation_why_prioritized),
    },
    {
      id: "pain",
      icon: "🩹",
      label: "Pain points detected",
      bullets: s.explanation_pain_points as any,
      tone: "default" as const,
      badge: count(s.explanation_pain_points),
    },
    {
      id: "maturity",
      icon: "📈",
      label: "Account journey",
      bullets: s.explanation_maturity as any,
      tone: "default" as const,
      badge: count(s.explanation_maturity),
    },
    {
      id: "triggers",
      icon: "⚡",
      label: "What changed recently",
      bullets: s.explanation_triggers as any,
      tone: "default" as const,
      badge: count(s.explanation_triggers),
    },
    {
      id: "strategic",
      icon: "🎯",
      label: "Why this matters",
      bullets: s.explanation_expansion_thesis as any,
      tone: "blue" as const,
      badge: count(s.explanation_expansion_thesis),
    },
    {
      id: "why_now",
      icon: "⏰",
      label: "Why act this week",
      prose: s.why_now,
      tone: "amber" as const,
    },
    {
      id: "whats_missing",
      icon: "🧩",
      label: "What's missing",
      prose: s.whats_missing,
      tone: "default" as const,
    },
    {
      id: "evidence",
      icon: "🔍",
      label: "Evidence the system used",
      bullets: s.supporting_context as any,
      tone: "default" as const,
      badge: count(s.supporting_context),
    },
  ];

  const tech = (
    <TechnicalDetailsContent
      reasoning_trace={s.reasoning_trace}
      business_logic={s.business_logic}
      ontology={s.ontology_grounding}
      modelMetadata={(s as any).model_metadata}
    />
  );

  return (
    <div className="space-y-4">
      {/* Header strip */}
      <header className="border border-white/10 rounded-lg px-5 py-4 flex flex-wrap items-center gap-4 justify-between bg-zinc-950">
        <div className="flex-1 min-w-[280px]">
          <Link href="/dashboard" className="text-xs text-gray-500 hover:underline">
            ← back to dashboard
          </Link>
          <h1 className="text-2xl font-bold mt-1">{s.account_name}</h1>
          <div className="flex gap-2 mt-1 flex-wrap items-center text-xs">
            <PriorityBadge band={s.priority_band} />
            <OwnerBadge owner={s.recommended_action_owner} />
            <span className="text-gray-500">
              Opportunity:{" "}
              <span className="text-gray-200 font-medium">{s.missing_use_case || "—"}</span>
            </span>
          </div>
        </div>
        <div className="flex gap-3 text-xs">
          <Stat label="Confidence" value={s.confidence?.toFixed(2) ?? "—"} />
          <Stat label="Final score" value={s.final_score?.toFixed(2) ?? "—"} />
          <Stat label="AE" value={s.ownership?.ae?.name || "—"} sub={s.ownership?.ae?.role} />
          <Stat label="CSM" value={s.ownership?.csm?.name || "—"} />
        </div>
      </header>

      {/* 2-column main: persistent ACTION on the left, tabbed INSIGHTS on the right */}
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_440px] gap-4 items-start">
        {/* ----- LEFT: persona + email (always visible) ----- */}
        <div className="space-y-4">
          {s.who_to_target?.primary && (
            <div className="border border-emerald-500/30 bg-emerald-500/5 rounded-lg p-5">
              <div className="text-xs uppercase text-emerald-300 mb-1 flex items-center gap-2">
                <span>👤</span>
                <span>Best persona to target</span>
              </div>
              <div className="text-xl font-bold">{s.who_to_target.primary.name}</div>
              <div className="text-gray-300">{s.who_to_target.primary.title}</div>
              <div className="flex gap-4 text-xs text-gray-400 mt-2 flex-wrap">
                <span>
                  <span className="text-gray-500">Buying role: </span>
                  <span className="font-medium text-gray-200 capitalize">
                    {s.who_to_target.primary.buying_role.replace("_", " ")}
                  </span>
                </span>
                <span>
                  <span className="text-gray-500">Source: </span>
                  <span className="font-medium text-gray-200">
                    {s.who_to_target.primary.source === "sf"
                      ? "Already a user (SF contact)"
                      : "ICP via Clay (not in product)"}
                  </span>
                </span>
                {s.who_to_target.primary.linkedin && (
                  <a
                    href={s.who_to_target.primary.linkedin}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-blue-400 underline"
                  >
                    LinkedIn ↗
                  </a>
                )}
              </div>
              <p className="text-sm mt-3 text-gray-200">
                <span className="text-gray-500">Why this person: </span>
                {s.who_to_target.primary.why_this_person}
              </p>
            </div>
          )}

          {s.draft_outreach && (
            <div className="border border-blue-500/30 bg-blue-500/5 rounded-lg overflow-hidden">
              <div className="px-4 py-2 border-b border-blue-500/20 flex items-center justify-between bg-blue-500/10">
                <span className="text-xs uppercase text-blue-300 flex items-center gap-2">
                  <span>✉️</span>
                  <span>Draft outreach email</span>
                </span>
                <CopyButton
                  text={`Subject: ${s.draft_outreach.subject}\n\n${s.draft_outreach.body}`}
                />
              </div>
              <div className="px-4 py-2 border-b border-blue-500/20 text-sm">
                <span className="text-gray-500 text-xs uppercase">Subject:</span>{" "}
                <span className="font-semibold text-gray-100">{s.draft_outreach.subject}</span>
              </div>
              {s.who_to_target?.primary && (
                <div className="bg-black/40 px-4 py-1.5 border-b border-blue-500/20 text-xs text-gray-400">
                  <span className="text-gray-500">To:</span> {s.who_to_target.primary.name}
                  {s.who_to_target.primary.title && (
                    <span className="text-gray-500"> · {s.who_to_target.primary.title}</span>
                  )}
                </div>
              )}
              <div className="px-4 py-3 font-mono text-[13px] whitespace-pre-wrap bg-black/40 text-gray-100 leading-relaxed max-h-[560px] overflow-y-auto">
                {s.draft_outreach.body}
              </div>
            </div>
          )}

          {/* Feedback strip — pinned to the action column */}
          <div className="border border-white/10 rounded-lg p-4 flex flex-wrap items-center justify-between gap-3 bg-zinc-950">
            <div>
              <div className="text-xs uppercase text-gray-500 mb-1">Your verdict</div>
              <FeedbackButtons signalId={s.id} runId={runId} />
            </div>
            <Link
              href={`/accounts/${s.account_id}`}
              className="text-xs text-gray-400 underline hover:text-gray-200"
            >
              View account context →
            </Link>
          </div>
        </div>

        {/* ----- RIGHT: insight tabs (one section at a time) ----- */}
        <aside className="xl:sticky xl:top-4 self-start">
          <div className="text-xs uppercase text-gray-500 mb-2 px-1">
            📑 Insight panels · click to explore
          </div>
          <InsightTabs sections={sections} technical={tech} />
        </aside>
      </div>
    </div>
  );
}

// ---------- helpers ----------

function Stat({ label, value, sub }: { label: string; value: any; sub?: string }) {
  return (
    <div className="border border-white/10 rounded px-3 py-2 min-w-[110px]">
      <div className="text-[10px] uppercase text-gray-500">{label}</div>
      <div className="font-semibold text-gray-100">{value}</div>
      {sub && <div className="text-[10px] text-gray-500 mt-0.5">{sub}</div>}
    </div>
  );
}

function TechnicalDetailsContent(props: {
  reasoning_trace?: string;
  business_logic?: string;
  ontology?: any;
  modelMetadata?: any;
}) {
  // Render the inline content (no surrounding card — InsightTabs provides it)
  const { reasoning_trace, business_logic, ontology, modelMetadata } = props;
  return (
    <div className="space-y-4 text-sm">
      {business_logic && (
        <div>
          <div className="text-xs uppercase text-gray-500 mb-1">
            Causal chain (data → outcome)
          </div>
          <p className="text-gray-200">{business_logic}</p>
        </div>
      )}
      {ontology && (
        <div className="grid grid-cols-2 gap-2 text-xs">
          {ontology.expansion_entity_id && (
            <TechCell label="Expansion entity" value={ontology.expansion_entity_id} mono />
          )}
          {ontology.persona_entity_id && (
            <TechCell label="Persona entity" value={ontology.persona_entity_id} mono />
          )}
          {ontology.maturity_stage && (
            <TechCell label="Maturity stage" value={`Stage ${ontology.maturity_stage}`} />
          )}
          {(ontology.primary_pain_ids?.length ?? 0) > 0 && (
            <TechCell
              label="Pain entities"
              value={ontology.primary_pain_ids?.join(", ") ?? ""}
              mono
            />
          )}
          {(ontology.trigger_ids?.length ?? 0) > 0 && (
            <TechCell
              label="Trigger entities"
              value={ontology.trigger_ids?.join(", ") ?? ""}
              mono
            />
          )}
          {ontology.causal_chain && (
            <TechCell label="Causal chain" value={ontology.causal_chain} />
          )}
          {ontology.competitor_referenced && (
            <TechCell label="Competitor" value={ontology.competitor_referenced} />
          )}
          {(ontology.churn_indicators_present?.length ?? 0) > 0 && (
            <TechCell
              label="Churn risks"
              value={ontology.churn_indicators_present?.join(", ") ?? ""}
              mono
              warn
            />
          )}
        </div>
      )}
      {reasoning_trace && (
        <div>
          <div className="text-xs uppercase text-gray-500 mb-1">Step-by-step agent trace</div>
          <p className="text-gray-400 italic border-l-2 border-white/20 pl-3">
            {reasoning_trace}
          </p>
        </div>
      )}
      {modelMetadata && (
        <div className="text-xs text-gray-500 flex gap-4 flex-wrap">
          <span>model={modelMetadata.model}</span>
          {modelMetadata.tokens_in !== undefined && (
            <span>
              tokens={modelMetadata.tokens_in}→{modelMetadata.tokens_out}
            </span>
          )}
          {modelMetadata.latency_ms !== undefined && (
            <span>latency={modelMetadata.latency_ms}ms</span>
          )}
        </div>
      )}
    </div>
  );
}

function TechCell({
  label,
  value,
  mono,
  warn,
}: {
  label: string;
  value: string;
  mono?: boolean;
  warn?: boolean;
}) {
  return (
    <div
      className={`border rounded px-2 py-1 ${
        warn ? "border-rose-500/40 bg-rose-500/10" : "border-white/10"
      }`}
    >
      <div className={warn ? "text-rose-300" : "text-gray-500"}>{label}</div>
      <div className={mono ? "font-mono text-gray-100" : "text-gray-100"}>{value}</div>
    </div>
  );
}
