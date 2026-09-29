import { useState } from "react";
import Badge from "./Badge.jsx";
import GateCard from "./GateCard.jsx";
import EvidenceColumns from "./EvidenceColumns.jsx";
import { fixLabel, formatTrust, riskMeta, verdictMeta } from "../lib/format.js";

function Row({ entry, isTop, expanded, onToggle, onExecute, executing }) {
  const ev = entry.evidence;
  const v = verdictMeta(ev.verdict);
  const risk = riskMeta(ev.risk_tier);
  return (
    <div
      className={`rounded-xl border bg-[var(--color-surface-1)]/70 transition-colors ${
        isTop ? "border-blue-500/35 ring-1 ring-blue-500/15" : "border-[var(--color-border-soft)]"
      }`}
    >
      <button onClick={onToggle} className="flex w-full flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 text-left sm:flex-nowrap">
        {isTop && <Badge color="#60a5fa" bg="rgba(59,130,246,0.12)" className="shrink-0">Top pick</Badge>}
        <span className="font-medium text-white">{fixLabel(ev.fix)}</span>
        <Badge color={risk.color} bg={risk.bg} className="shrink-0">{risk.label}</Badge>
        <span className="flex flex-1 flex-wrap items-center justify-end gap-x-3 gap-y-1.5 sm:ml-auto">
          <span className="text-xs text-[var(--color-text-faint)] sm:text-sm">
            {ev.passed.count} pass / {ev.failed.count} fail
          </span>
          <Badge color={v.color} bg={v.bg} border={v.border}>{v.label}</Badge>
          <span className="mono w-12 text-right text-sm font-semibold text-slate-200">T={formatTrust(ev.trust)}</span>
          <span className="text-[var(--color-text-faint)]">{expanded ? "−" : "+"}</span>
        </span>
      </button>
      {expanded && (
        <div className="space-y-3 border-t border-[var(--color-border-soft)] px-4 py-3.5">
          <EvidenceColumns evidence={ev} />
          <GateCard gate={entry.gate} />
          {onExecute && (
            <button
              onClick={() => onExecute(ev.fix)}
              disabled={executing}
              className="rounded-md bg-blue-600 px-3.5 py-2 text-xs font-semibold text-white shadow-md shadow-blue-950/40 hover:bg-blue-500 disabled:opacity-50"
            >
              {executing ? "Executing…" : `Execute ${fixLabel(ev.fix)}`}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function TrustLedger({ rankedFixes, onExecute, executing }) {
  const [openFix, setOpenFix] = useState(rankedFixes[0]?.evidence.fix ?? null);
  return (
    <div className="space-y-2">
      {rankedFixes.map((entry, i) => (
        <Row
          key={entry.evidence.fix}
          entry={entry}
          isTop={i === 0}
          expanded={openFix === entry.evidence.fix}
          onToggle={() => setOpenFix(openFix === entry.evidence.fix ? null : entry.evidence.fix)}
          onExecute={onExecute}
          executing={executing === entry.evidence.fix}
        />
      ))}
    </div>
  );
}
