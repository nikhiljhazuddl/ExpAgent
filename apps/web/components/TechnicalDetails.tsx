"use client";

import { useState } from "react";

type Props = {
  reasoning_trace?: string;
  business_logic?: string;
  ontology?: {
    expansion_entity_id?: string;
    primary_pain_ids?: string[];
    trigger_ids?: string[];
    persona_entity_id?: string;
    competitor_referenced?: string;
    maturity_stage?: number;
    churn_indicators_present?: string[];
    causal_chain?: string;
  };
  modelMetadata?: {
    model?: string;
    tokens_in?: number;
    tokens_out?: number;
    latency_ms?: number;
  };
};

export function TechnicalDetails({
  reasoning_trace,
  business_logic,
  ontology,
  modelMetadata,
}: Props) {
  const [open, setOpen] = useState(false);
  if (!reasoning_trace && !business_logic && !ontology) return null;

  return (
    <section className="border border-white/10 rounded">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-white/5 text-left"
      >
        <span className="text-xs uppercase text-gray-500">
          🔧 Technical details · internal taxonomy
        </span>
        <span className="text-xs text-gray-500">{open ? "Hide" : "Show"}</span>
      </button>
      {open && (
        <div className="border-t border-white/10 p-4 space-y-4 text-sm">
          {business_logic && (
            <div>
              <div className="text-xs uppercase text-gray-500 mb-1">
                Causal chain (data → outcome)
              </div>
              <p className="text-gray-200">{business_logic}</p>
            </div>
          )}
          {ontology && (
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 text-xs">
              {ontology.expansion_entity_id && (
                <Cell label="Expansion entity" value={ontology.expansion_entity_id} mono />
              )}
              {ontology.persona_entity_id && (
                <Cell label="Persona entity" value={ontology.persona_entity_id} mono />
              )}
              {ontology.maturity_stage && (
                <Cell label="Maturity stage" value={`Stage ${ontology.maturity_stage}`} />
              )}
              {(ontology.primary_pain_ids?.length ?? 0) > 0 && (
                <Cell
                  label="Pain entities"
                  value={ontology.primary_pain_ids?.join(", ") ?? ""}
                  mono
                />
              )}
              {(ontology.trigger_ids?.length ?? 0) > 0 && (
                <Cell label="Trigger entities" value={ontology.trigger_ids?.join(", ") ?? ""} mono />
              )}
              {ontology.causal_chain && (
                <Cell label="Causal chain" value={ontology.causal_chain} />
              )}
              {ontology.competitor_referenced && (
                <Cell label="Competitor" value={ontology.competitor_referenced} />
              )}
              {(ontology.churn_indicators_present?.length ?? 0) > 0 && (
                <Cell
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
              <div className="text-xs uppercase text-gray-500 mb-1">
                Step-by-step agent trace
              </div>
              <p className="text-gray-400 italic border-l-2 border-white/20 pl-3">
                {reasoning_trace}
              </p>
            </div>
          )}
          {modelMetadata && (
            <div className="text-xs text-gray-500 flex gap-4">
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
      )}
    </section>
  );
}

function Cell({
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
