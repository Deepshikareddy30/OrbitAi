import Badge from "./Badge.jsx";

const STRENGTH_COLOR = { Strong: "#f87171", Moderate: "#fbbf24", Weak: "#94a3b8" };

/** Derived entirely from the incident's own real fields (changes_before, contributing_
 * factors) - not a separate diagnosis model. A recent, confirmed change is "Strong"
 * evidence of cause; a noted contributing factor not tied to a specific change is
 * "Moderate". No fabricated third option - if there's nothing beyond that, there isn't. */
export default function PotentialCauses({ incident }) {
  const causes = [];
  for (const c of incident.changes_before || []) {
    causes.push({
      label: `${c.type.replace(/_/g, " ")}: ${c.detail}`,
      detail: `${c.minutes_before} minutes before the incident`,
      strength: "Strong",
    });
  }
  const changeFactors = new Set(
    (incident.changes_before || []).map((c) => (c.type === "deploy" ? "recent_deploy" : c.type))
  );
  for (const f of incident.contributing_factors || []) {
    if (changeFactors.has(f)) continue; // already represented by a changes_before entry
    causes.push({ label: f.replace(/_/g, " "), detail: "noted in the incident's contributing factors", strength: "Moderate" });
  }

  if (causes.length === 0) {
    return <p className="text-sm text-[var(--color-text-faint)]">No specific cause signals identified from the incident context.</p>;
  }

  return (
    <ol className="space-y-2">
      {causes.map((c, i) => (
        <li key={i} className="flex items-start justify-between gap-3 rounded-lg border border-[var(--color-border-soft)] bg-black/20 p-3">
          <div>
            <div className="text-sm font-medium capitalize text-slate-100">{i + 1}. {c.label}</div>
            <div className="text-xs text-[var(--color-text-faint)]">{c.detail}</div>
          </div>
          <Badge color={STRENGTH_COLOR[c.strength]} bg={`${STRENGTH_COLOR[c.strength]}22`} className="shrink-0">
            {c.strength}
          </Badge>
        </li>
      ))}
    </ol>
  );
}
