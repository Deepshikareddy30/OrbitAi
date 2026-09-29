import { useState } from "react";
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ScatterChart, Scatter, ReferenceLine,
} from "recharts";
import { api } from "../api.js";
import { useAsync } from "../lib/useAsync.js";
import { Loading, ErrorBox } from "../components/Status.jsx";
import Card from "../components/Card.jsx";
import Badge from "../components/Badge.jsx";
import StatTile from "../components/StatTile.jsx";
import { formatPct, verdictMeta, fixLabel } from "../lib/format.js";

const BASELINE_COLOR = "#64748b";
const TRUSTLENS_COLOR = "#60a5fa";
const GRID_COLOR = "#1e293b";
const AXIS_TICK = { fontSize: 11, fill: "#5b6478" };

function ContributionBadge({ value }) {
  const abs = Math.abs(value);
  const strength = abs >= 1.0 ? "High" : abs >= 0.4 ? "Moderate" : "Low";
  const dir = value > 0 ? "boosts" : value < 0 ? "reduces" : "neutral";
  const color = value > 0 ? "#4ade80" : value < 0 ? "#f87171" : "#94a3b8";
  return (
    <Badge color={color} bg={`${color}22`}>
      {strength} {dir !== "neutral" ? `· ${dir}` : ""}
    </Badge>
  );
}

function ComparisonTile({ label, baseline, trustlens, fmt = (x) => x, lowerBetter = false }) {
  const better = lowerBetter ? trustlens < baseline : trustlens > baseline;
  const tied = trustlens === baseline;
  return (
    <div className="rounded-xl border border-[var(--color-border-soft)] bg-[var(--color-surface-1)]/70 p-4 shadow-lg shadow-black/20">
      <div className="text-xs font-medium uppercase tracking-wide text-[var(--color-text-faint)]">{label}</div>
      <div className="mt-1.5 flex items-baseline gap-2">
        <span className="text-2xl font-semibold text-white">{fmt(trustlens)}</span>
        <span className="text-xs text-[var(--color-text-faint)]">vs {fmt(baseline)} baseline</span>
      </div>
      <div className={`mt-1 text-xs font-medium ${better ? "text-emerald-400" : tied ? "text-[var(--color-text-faint)]" : "text-[var(--color-text-muted)]"}`}>
        {tied ? "even" : better ? "↑ OrbitAI ahead" : "baseline ahead"}
      </div>
    </div>
  );
}

export default function AIHealthPage() {
  const { data, error, loading, reload } = useAsync(() => api.evalResults(), []);

  if (loading) return <Loading label="Loading evaluation results…" />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;

  const agg = data.aggregates;
  const cumulative = agg.cumulative_p_success.baseline.map((b, i) => ({
    i: i + 1, baseline: b, trustlens: agg.cumulative_p_success.trustlens[i],
  }));
  const learning = agg.learning_curve || [];
  const calibration = agg.calibration || [];

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold text-white">AI Health</h1>
        <p className="mt-1 text-sm text-[var(--color-text-muted)]">
          Simulated replay evaluation — {data.meta.n_held_out} held-out incidents, replayed in time order.
          Baseline: {data.meta.base_llm}. Memory: {data.meta.memory_store}.
        </p>
        {data.meta.note && (
          <p className="mt-1 max-w-3xl text-xs text-amber-400/80">{data.meta.note}</p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <ComparisonTile label="Best-fix rate" baseline={agg.best_fix_rate.baseline} trustlens={agg.best_fix_rate.trustlens} fmt={(x) => formatPct(x)} />
        <ComparisonTile label="Mean p(success)" baseline={agg.mean_p_success.baseline} trustlens={agg.mean_p_success.trustlens} fmt={(x) => formatPct(x)} />
        <ComparisonTile label="Mean regret" baseline={agg.mean_regret.baseline} trustlens={agg.mean_regret.trustlens} fmt={(x) => x.toFixed(3)} lowerBetter />
        <StatTile label="Escalation rate" value={formatPct(agg.escalation.rate)}
                 sub={agg.escalation.accuracy_on_non_escalated != null ? `${formatPct(agg.escalation.accuracy_on_non_escalated)} accurate when not escalated` : undefined} />
      </div>

      {agg.lookalike_subset?.n > 0 && (
        <Card
          title="Look-alike trap subset"
          subtitle={`${agg.lookalike_subset.n} incidents with the deliberately ambiguous memory-leak / bad-deploy symptom`}
        >
          <div className="flex flex-wrap items-center gap-6">
            <div>
              <div className="text-xs text-[var(--color-text-faint)]">Baseline best-fix rate</div>
              <div className="text-xl font-semibold text-slate-400">{formatPct(agg.lookalike_subset.baseline_best_fix_rate)}</div>
            </div>
            <div>
              <div className="text-xs text-[var(--color-text-faint)]">OrbitAI best-fix rate</div>
              <div className="text-xl font-semibold text-blue-400">{formatPct(agg.lookalike_subset.trustlens_best_fix_rate)}</div>
            </div>
            <div>
              <div className="text-xs text-[var(--color-text-faint)]">OrbitAI flags conflict</div>
              <div className="text-xl font-semibold text-amber-400">{formatPct(agg.lookalike_subset.trustlens_conflict_rate)}</div>
            </div>
            <p className="max-w-sm text-xs text-[var(--color-text-muted)]">
              This is the case plain similarity search would get wrong: the courtroom-style two-sided evidence catches
              it and escalates instead of confidently recommending the wrong fix.
            </p>
          </div>
        </Card>
      )}

      <Card title="Cumulative recommendation quality" subtitle="Mean p(success) of the top pick, cumulative over held-out incidents in time order">
        <ResponsiveContainer width="100%" height={260}>
          <LineChart data={cumulative} margin={{ left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
            <XAxis dataKey="i" tick={AXIS_TICK} label={{ value: "held-out incident #", position: "insideBottom", offset: -2, fontSize: 11, fill: "#5b6478" }} />
            <YAxis domain={[0, 1]} tick={AXIS_TICK} />
            <Tooltip formatter={(v) => v.toFixed(3)} contentStyle={{ background: "#161d2e", border: "1px solid #22293c", borderRadius: 8, fontSize: 12 }} labelStyle={{ color: "#8b96ab" }} />
            <Legend wrapperStyle={{ fontSize: 12, color: "#8b96ab" }} />
            <Line type="monotone" dataKey="baseline" name="Baseline (no memory)" stroke={BASELINE_COLOR} strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="trustlens" name="OrbitAI (Hindsight memory)" stroke={TRUSTLENS_COLOR} strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </Card>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        {learning.length > 0 && (
          <Card title="Learning curve" subtitle="Does more training history help?">
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={learning} margin={{ left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
                <XAxis dataKey="n_train" tick={AXIS_TICK} label={{ value: "training incidents", position: "insideBottom", offset: -2, fontSize: 11, fill: "#5b6478" }} />
                <YAxis domain={[0, 1]} tick={AXIS_TICK} />
                <Tooltip formatter={(v) => v.toFixed(3)} contentStyle={{ background: "#161d2e", border: "1px solid #22293c", borderRadius: 8, fontSize: 12 }} labelStyle={{ color: "#8b96ab" }} />
                <Line type="monotone" dataKey="mean_p_success" name="mean p(success)" stroke={TRUSTLENS_COLOR} strokeWidth={2} dot={{ r: 3, fill: TRUSTLENS_COLOR }} />
              </LineChart>
            </ResponsiveContainer>
          </Card>
        )}

        {calibration.length > 0 && (
          <Card title="Trust score calibration" subtitle={`Brier=${agg.brier} · AUC=${agg.auc}`}>
            <ResponsiveContainer width="100%" height={240}>
              <ScatterChart margin={{ left: -10 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={GRID_COLOR} />
                <XAxis dataKey="mean_predicted" type="number" domain={[0, 1]} tick={AXIS_TICK} name="predicted trust" />
                <YAxis dataKey="actual_rate" type="number" domain={[0, 1]} tick={AXIS_TICK} name="actual resolved rate" />
                <Tooltip formatter={(v) => v.toFixed(2)} cursor={{ strokeDasharray: "3 3", stroke: "#334155" }} contentStyle={{ background: "#161d2e", border: "1px solid #22293c", borderRadius: 8, fontSize: 12 }} labelStyle={{ color: "#8b96ab" }} />
                <ReferenceLine segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]} stroke="#334155" strokeDasharray="4 4" />
                <Scatter data={calibration} fill={TRUSTLENS_COLOR} />
              </ScatterChart>
            </ResponsiveContainer>
          </Card>
        )}
      </div>

      {agg.weight_recovery && (
        <Card title="Factor contribution" subtitle="How strongly each factor influences a fix recommendation, learned vs. the hidden simulator's true behavior">
          <div className="mb-3 text-sm text-[var(--color-text-muted)]">
            Correlation: <span className="font-mono font-semibold text-blue-400">{agg.weight_recovery.correlation}</span>
            {" "}across {agg.weight_recovery.n_pairs} known factor → fix pairs
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[420px] text-left text-xs">
              <thead className="text-[var(--color-text-faint)]">
                <tr>
                  <th className="py-1 font-medium">Factor</th>
                  <th className="py-1 font-medium">Fix</th>
                  <th className="py-1 font-medium">True contribution</th>
                  <th className="py-1 font-medium">Learned contribution</th>
                </tr>
              </thead>
              <tbody>
                {agg.weight_recovery.pairs.map((p, i) => (
                  <tr key={i} className="border-t border-[var(--color-border-soft)]">
                    <td className="py-1.5 font-mono text-slate-300">{p.factor}</td>
                    <td className="py-1.5 text-slate-300">{fixLabel(p.fix)}</td>
                    <td className="py-1.5"><ContributionBadge value={p.true} /></td>
                    <td className="py-1.5"><ContributionBadge value={p.learned} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      <IncidentLevelEval incidents={data.incidents} />
    </div>
  );
}

function IncidentLevelEval({ incidents }) {
  const [selected, setSelected] = useState(incidents[0]?.id ?? null);
  const row = incidents.find((r) => r.id === selected);

  return (
    <Card title="Incident-level evaluation" subtitle="Pick any held-out incident to see baseline vs OrbitAI side by side">
      <select
        value={selected ?? ""}
        onChange={(e) => setSelected(e.target.value)}
        className="mb-3 rounded-md border border-[var(--color-border-soft)] bg-black/30 px-2 py-1.5 text-sm text-slate-200"
      >
        {incidents.map((r) => (
          <option key={r.id} value={r.id} className="bg-[var(--color-surface-1)]">{r.id}</option>
        ))}
      </select>
      {row && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="rounded-lg border border-[var(--color-border-soft)] bg-black/20 p-3.5">
            <Badge color={BASELINE_COLOR} bg="rgba(100,116,139,0.15)">Baseline</Badge>
            <div className="mt-2 text-sm font-medium text-white">{fixLabel(row.baseline.fix)}</div>
            <div className="mt-1 text-xs text-[var(--color-text-muted)]">
              p(success)={row.baseline.p_success} · regret={row.baseline.regret} · best={row.baseline.is_best ? "yes" : "no"}
            </div>
            <div className="mt-1 text-[11px] text-[var(--color-text-faint)]">{row.baseline.used_llm ? "LLM call" : "heuristic fallback"}</div>
          </div>
          <div className="rounded-lg border border-blue-500/25 bg-blue-500/[0.06] p-3.5">
            <Badge color={TRUSTLENS_COLOR} bg="rgba(59,130,246,0.12)">OrbitAI</Badge>
            <div className="mt-2 text-sm font-medium text-white">{fixLabel(row.trustlens.fix)}</div>
            <div className="mt-1 text-xs text-[var(--color-text-muted)]">
              p(success)={row.trustlens.p_success} · regret={row.trustlens.regret} · best={row.trustlens.is_best ? "yes" : "no"}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-[var(--color-text-faint)]">
              <Badge color={verdictMeta(row.trustlens.verdict).color} bg={verdictMeta(row.trustlens.verdict).bg}>
                {verdictMeta(row.trustlens.verdict).label}
              </Badge>
              T={row.trustlens.T} · gate={row.trustlens.gate}
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
