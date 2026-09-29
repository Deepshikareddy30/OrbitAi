import Badge from "./Badge.jsx";
import { formatPct } from "../lib/format.js";

const STRENGTH_COLOR = { HIGH: "#f87171", MODERATE: "#fbbf24", LOW: "#4ade80", STRONG: "#4ade80", WEAK: "#94a3b8" };

function StrengthBadge({ label }) {
  const color = STRENGTH_COLOR[label] || "#94a3b8";
  return <Badge color={color} bg={`${color}22`}>{label}</Badge>;
}

/** Presentational only - the courtroom result arrives pre-computed as part of the
 * agent's /start response (auto-triggered when should_convene() says so), no separate
 * fetch or button needed here. */
export default function CourtroomResult({ result }) {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-emerald-500/25 bg-emerald-500/[0.06] p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-emerald-300">
            🛡 Advocate
            {!result.advocate_used_llm && <span className="text-[10px] font-normal text-[var(--color-text-faint)]">(fallback)</span>}
          </div>
          <p className="text-sm text-slate-200">{result.advocate_text}</p>
        </div>
        <div className="rounded-lg border border-orange-500/25 bg-orange-500/[0.06] p-4">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold text-orange-300">
            ⚖ Challenger
            {!result.challenger_used_llm && <span className="text-[10px] font-normal text-[var(--color-text-faint)]">(fallback)</span>}
          </div>
          <p className="text-sm text-slate-200">{result.challenger_text}</p>
        </div>
      </div>

      <div className="rounded-lg border border-[var(--color-border-soft)] bg-black/20 p-4">
        <div className="mb-3 text-xs font-semibold uppercase tracking-wide text-[var(--color-text-faint)]">
          Courtroom Assessment
        </div>
        <div className="grid grid-cols-3 gap-3 text-center">
          <div>
            <div className="text-[11px] text-[var(--color-text-faint)]">Evidence strength</div>
            <div className="mt-1"><StrengthBadge label={result.evidence_strength} /></div>
          </div>
          <div>
            <div className="text-[11px] text-[var(--color-text-faint)]">Historical support</div>
            <div className="mt-1"><StrengthBadge label={result.historical_support} /></div>
          </div>
          <div>
            <div className="text-[11px] text-[var(--color-text-faint)]">Conflicting evidence</div>
            <div className="mt-1"><StrengthBadge label={result.conflicting_evidence} /></div>
          </div>
        </div>
        <div className="mt-4 flex items-center justify-center gap-4 border-t border-[var(--color-border-soft)] pt-3">
          <div className="text-center">
            <div className="text-[11px] text-[var(--color-text-faint)]">Base trust</div>
            <div className="mono text-lg text-slate-300">{formatPct(result.base_trust)}</div>
          </div>
          <div className="text-center">
            <div className="text-[11px] text-[var(--color-text-faint)]">Adjustment</div>
            <div className={`mono text-lg ${result.trust_adjustment < 0 ? "text-red-400" : "text-emerald-400"}`}>
              {result.trust_adjustment >= 0 ? "+" : ""}{formatPct(result.trust_adjustment)}
            </div>
          </div>
          <div className="text-center">
            <div className="text-[11px] text-[var(--color-text-faint)]">Final trust</div>
            <div className="mono text-2xl font-semibold text-white">{formatPct(result.final_trust)}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
