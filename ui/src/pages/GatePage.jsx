import { api } from "../api.js";
import { useAsync } from "../lib/useAsync.js";
import { Loading, ErrorBox } from "../components/Status.jsx";
import Card from "../components/Card.jsx";
import Badge from "../components/Badge.jsx";
import { gateMeta, riskMeta } from "../lib/format.js";

const RISK_ORDER = ["low", "medium", "high"];

export default function GatePage() {
  const { data, error, loading, reload } = useAsync(() => api.gateConfig(), []);

  if (loading) return <Loading label="Loading gate config…" />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-white">Adaptive Approval Gate</h1>
        <p className="mt-1 max-w-2xl text-sm text-[var(--color-text-muted)]">
          Routes by blast radius and reversibility, not a change-board. Fast, tiered, and never blocks on paperwork.
          This is real routing logic (see engine/gate.py) evaluated per-recommendation on the incident page —
          shown here as a reference table.
        </p>
      </div>

      <Card title="Risk tier rules">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {RISK_ORDER.map((tier) => {
            const rule = data.risk_rules[tier];
            const risk = riskMeta(tier);
            const trusted = gateMeta(rule.if_trusted);
            const otherwise = gateMeta(rule.otherwise);
            return (
              <div key={tier} className="rounded-lg border border-[var(--color-border-soft)] bg-black/20 p-3.5">
                <Badge color={risk.color} bg={risk.bg}>{risk.label}</Badge>
                <div className="mt-3 space-y-2.5 text-sm">
                  <div>
                    <div className="text-xs text-[var(--color-text-faint)]">If trust ≥ {rule.trust_threshold} and verdict agrees</div>
                    <div className="font-medium text-white">{trusted.label}</div>
                  </div>
                  <div>
                    <div className="text-xs text-[var(--color-text-faint)]">Otherwise</div>
                    <div className="font-medium text-white">{otherwise.label}</div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </Card>

      <Card title="Modifiers">
        <ul className="space-y-3 text-sm text-[var(--color-text-muted)]">
          <li>
            <span className="font-medium text-white">Staging</span> relaxes one level (auto_run &lt; one_click &lt; escalate_ic &lt; two_person).
            Production uses the table as written.
          </li>
          <li>
            <span className="font-medium text-white">Conflict / no-evidence</span> verdicts force at least
            one-click human approval, applied after the staging relaxation — it always wins.
          </li>
          <li>
            <span className="font-medium text-white">Unanswered approvals</span> escalate to the next tier after a
            timeout (simulated timer):
            {" "}
            {Object.entries(data.timeouts_min).map(([action, min], i, arr) => (
              <span key={action}>
                <span className="font-mono text-slate-300">{gateMeta(action).label}</span> {min}min{i < arr.length - 1 ? ", " : ""}
              </span>
            ))}
          </li>
          <li>
            <span className="font-medium text-white">Break-glass</span> path bypasses the gate entirely for a
            true emergency — always requires a post-incident review entry.
          </li>
        </ul>
      </Card>
    </div>
  );
}
