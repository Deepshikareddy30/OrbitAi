import Badge from "./Badge.jsx";
import { formatTrust, gateMeta, riskMeta, verdictMeta } from "../lib/format.js";

export default function GateCard({ gate }) {
  const g = gateMeta(gate.action);
  const risk = riskMeta(gate.risk_tier);
  const v = verdictMeta(gate.verdict);
  return (
    <div className="rounded-lg border border-[var(--color-border-soft)] bg-black/20 p-3.5">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-white">{g.label}</div>
          <div className="text-xs text-[var(--color-text-muted)]">{g.detail}</div>
        </div>
        <Badge color={risk.color} bg={risk.bg} className="shrink-0">{risk.label}</Badge>
      </div>
      <div className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[var(--color-text-muted)]">
        <span>Notify: <span className="font-medium text-slate-200">{gate.notify.replace(/_/g, " ")}</span></span>
        {gate.timeout_min != null && <span>Timeout: <span className="font-medium text-slate-200">{gate.timeout_min}min</span></span>}
        {gate.relaxed_for_staging && <span className="text-cyan-400">relaxed (staging)</span>}
        {gate.floored_by_verdict && <span className="text-amber-400">floored (conflict/no-evidence)</span>}
      </div>
      <div className="mt-2.5 border-t border-[var(--color-border-soft)] pt-2 text-xs text-[var(--color-text-faint)]">
        Verdict: <span className="font-medium text-slate-300">{v.label}</span> · Trust <span className="mono text-slate-300">{formatTrust(gate.trust)}</span>
      </div>
    </div>
  );
}
