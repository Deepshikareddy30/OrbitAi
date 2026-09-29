import { Link } from "react-router-dom";
import Badge from "./Badge.jsx";
import { outcomeColor } from "../lib/format.js";

function SideColumn({ title, side, tone }) {
  const toneColor = tone === "pass" ? "#4ade80" : "#f87171";
  return (
    <div className="flex-1 rounded-lg border border-[var(--color-border-soft)] bg-black/20 p-3.5">
      <div className="mb-2.5 flex items-center justify-between">
        <div className="text-xs font-semibold uppercase tracking-wide text-[var(--color-text-muted)]">{title}</div>
        <Badge color={side.label === "high" ? toneColor : "#94a3b8"} bg={side.label === "high" ? `${toneColor}22` : "rgba(148,163,184,0.12)"}>
          {side.label} · {side.count} case{side.count === 1 ? "" : "s"}
        </Badge>
      </div>
      <div className="mb-2.5 text-xs text-[var(--color-text-muted)]">
        Mean similarity of top cases: <span className="font-mono text-slate-200">{side.mean_top_sim.toFixed(2)}</span>
      </div>
      {side.cases.length === 0 ? (
        <div className="text-xs text-[var(--color-text-faint)]">No cited cases.</div>
      ) : (
        <ul className="space-y-1.5">
          {side.cases.map((c) => (
            <li key={c.incident_id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 rounded-md border border-[var(--color-border-soft)] bg-[var(--color-surface-2)]/60 px-2.5 py-1.5 text-xs">
              <Link to={`/incidents/${c.incident_id}`} className="font-medium text-blue-400 hover:text-blue-300 hover:underline">
                {c.incident_id}
              </Link>
              <span className="flex items-center gap-2 text-[var(--color-text-muted)]">
                <span style={{ color: outcomeColor(c.outcome) }} className="font-medium">{c.outcome}</span>
                <span className="font-mono">sim {c.sim.toFixed(2)}</span>
                {c.time_to_recover_min != null && <span className="text-[var(--color-text-faint)]">{c.time_to_recover_min}m</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function EvidenceColumns({ evidence }) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row">
      <SideColumn title="Passed — for" side={evidence.passed} tone="pass" />
      <SideColumn title="Failed — against" side={evidence.failed} tone="fail" />
    </div>
  );
}
