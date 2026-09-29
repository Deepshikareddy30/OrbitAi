import { Link } from "react-router-dom";
import Badge from "./Badge.jsx";
import { outcomeColor, formatPct } from "../lib/format.js";

export default function SimilarIncidentsList({ incidents }) {
  if (!incidents || incidents.length === 0) {
    return <p className="text-sm text-[var(--color-text-faint)]">No similar historical incidents recalled.</p>;
  }
  return (
    <div className="space-y-2">
      {incidents.map((s) => (
        <Link
          key={s.incident_id}
          to={`/incidents/${s.incident_id}`}
          className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[var(--color-border-soft)] bg-black/20 p-3 transition-colors hover:border-blue-500/30 hover:bg-white/[0.03]"
        >
          <div>
            <div className="flex items-center gap-2">
              <span className="font-medium text-blue-400">{s.incident_id}</span>
              <Badge color="#60a5fa" bg="rgba(59,130,246,0.12)">{formatPct(s.similarity)} similar</Badge>
            </div>
            <div className="mt-1 text-xs text-[var(--color-text-muted)]">{s.why_relevant}</div>
          </div>
          <div className="flex items-center gap-2 text-sm">
            <span className="text-[var(--color-text-faint)]">{s.action.replace(/_/g, " ")}</span>
            <span style={{ color: outcomeColor(s.outcome) }} className="font-semibold">
              {s.outcome === "resolved" ? "PASSED ✓" : s.outcome === "recurred" ? "RECURRED ↻" : "FAILED ✕"}
            </span>
          </div>
        </Link>
      ))}
    </div>
  );
}
