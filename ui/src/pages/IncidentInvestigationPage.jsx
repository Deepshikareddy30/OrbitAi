import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api.js";
import { useAsync } from "../lib/useAsync.js";
import { Loading, ErrorBox } from "../components/Status.jsx";
import Card from "../components/Card.jsx";
import Badge from "../components/Badge.jsx";
import GateCard from "../components/GateCard.jsx";
import EvidenceColumns from "../components/EvidenceColumns.jsx";
import ProcessSteps from "../components/ProcessSteps.jsx";
import PotentialCauses from "../components/PotentialCauses.jsx";
import SimilarIncidentsList from "../components/SimilarIncidentsList.jsx";
import CourtroomResult from "../components/CourtroomResult.jsx";
import { fixLabel, formatDate, formatPct, formatTrust, riskMeta, verdictMeta, outcomeColor } from "../lib/format.js";

function SymptomStat({ label, value }) {
  return (
    <div className="rounded-md border border-[var(--color-border-soft)] bg-black/20 px-2.5 py-1.5 text-center">
      <div className="text-[10px] uppercase tracking-wide text-[var(--color-text-faint)]">{label}</div>
      <div className="mono text-sm font-semibold text-slate-100">{value}</div>
    </div>
  );
}

function IncidentContext({ inc }) {
  return (
    <Card title="Incident Context">
      <div className="space-y-3.5">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex gap-2">
            <SymptomStat label="p99" value={`${inc.symptoms.p99_ms}ms`} />
            <SymptomStat label="errors" value={formatPct(inc.symptoms.error_rate, 1)} />
            <SymptomStat label="cpu" value={formatPct(inc.symptoms.cpu)} />
            <SymptomStat label="mem" value={formatPct(inc.symptoms.mem)} />
          </div>
        </div>

        {inc.changes_before.length > 0 && (
          <div className="rounded-md border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
            <span className="font-semibold text-amber-300">Changes before:</span>{" "}
            {inc.changes_before.map((c) => `${c.type.replace(/_/g, " ")} ${c.detail} (${c.minutes_before}m before)`).join("; ")}
          </div>
        )}

        {inc.contributing_factors?.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {inc.contributing_factors.map((f) => (
              <Badge key={f} color="#cbd5e1" bg="rgba(148,163,184,0.1)">{f.replace(/_/g, " ")}</Badge>
            ))}
          </div>
        )}

        {inc.slack_thread?.length > 0 && (
          <div className="space-y-1 rounded-md border border-[var(--color-border-soft)] bg-black/25 p-2.5 font-mono text-xs text-[var(--color-text-muted)]">
            {inc.slack_thread.map((line, i) => (
              <div key={i}>#war-room: {line}</div>
            ))}
          </div>
        )}

        {inc.attempts?.length > 0 && (
          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--color-text-faint)]">Prior attempts on record</div>
            <ul className="space-y-1">
              {inc.attempts.map((a, i) => (
                <li key={i} className="flex flex-wrap items-center gap-2 text-sm">
                  <span style={{ color: outcomeColor(a.outcome) }} className="font-medium">{a.outcome}</span>
                  <span className="text-slate-300">{a.fix.replace(/_/g, " ")}</span>
                  {!a.verified && <Badge color="#f87171" bg="rgba(248,113,113,0.12)">unverified — excluded</Badge>}
                  {a.time_to_recover_min != null && <span className="text-xs text-[var(--color-text-faint)]">{a.time_to_recover_min}m</span>}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Card>
  );
}

function whyRecommend(rec) {
  const { passed, failed, verdict } = rec;
  const total = passed.count + failed.count;
  const reasons = [];
  if (passed.count > 0) {
    reasons.push(
      total > 0
        ? `${passed.count} of ${total} comparable historical incident${total === 1 ? "" : "s"} succeeded with this fix`
        : `${passed.count} historical incident${passed.count === 1 ? "" : "s"} succeeded with this fix`,
    );
  }
  if (passed.mean_top_sim > 0) {
    reasons.push(`Mean similarity to the successful cases: ${(passed.mean_top_sim * 100).toFixed(0)}%`);
  }
  if (failed.count > 0) {
    reasons.push(`${failed.count} conflicting case${failed.count === 1 ? "" : "s"} on record — factored into the trust score below`);
  } else if (verdict === "agree_trust") {
    reasons.push("No conflicting historical evidence found");
  }
  if (verdict === "no_evidence") {
    reasons.push("No directly comparable historical cases — trust reflects that uncertainty");
  }
  return reasons;
}

function RecommendationBody({ rec, gate }) {
  const v = verdictMeta(rec.verdict);
  const risk = riskMeta(rec.risk_tier);
  const reasons = whyRecommend(rec);
  return (
    <div className="space-y-3.5">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-lg font-semibold text-white">{fixLabel(rec.fix)}</span>
        <Badge color={risk.color} bg={risk.bg}>{risk.label}</Badge>
        <Badge color={v.color} bg={v.bg} border={v.border}>{v.label}</Badge>
        <span className="mono ml-auto text-xl font-semibold text-slate-100">T={formatTrust(rec.trust)}</span>
      </div>
      {reasons.length > 0 && (
        <div className="rounded-lg border border-[var(--color-border-soft)] bg-black/20 p-3.5">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-text-faint)]">Why OrbitAI recommends this</div>
          <ul className="space-y-1.5 text-sm text-slate-300">
            {reasons.map((r, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-blue-400">•</span>
                <span>{r}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      <EvidenceColumns evidence={rec} />
      {gate && <GateCard gate={gate} />}
    </div>
  );
}

function Outcome({ status, executionResult, observedOutcome, memoryUpdate, humanAction, fix }) {
  if (status === "rejected") {
    return (
      <p className="text-sm text-[var(--color-text-muted)]">
        Recommendation rejected{humanAction?.reason ? ` — ${humanAction.reason}` : ""} — no action taken, logged to the audit trail.
      </p>
    );
  }
  return (
    <div className="space-y-4">
      <div className="text-sm">
        Executed <span className="font-medium text-slate-100">{fixLabel(executionResult?.fix || fix || "")}</span>
        {observedOutcome && (
          <>
            {" "}—{" "}
            <span style={{ color: outcomeColor(observedOutcome.outcome) }} className="font-semibold">
              {observedOutcome.outcome === "resolved" ? "✓ Incident resolved" : observedOutcome.outcome === "recurred" ? "↻ Incident recurred" : "✗ Incident persisted"}
            </span>
            {observedOutcome.time_to_recover_min != null && <span className="text-[var(--color-text-faint)]"> · {observedOutcome.time_to_recover_min}m to recover</span>}
          </>
        )}
      </div>

      {memoryUpdate && (
        <div className="rounded-lg border border-[var(--color-border-soft)] bg-black/20 p-3.5">
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--color-text-faint)]">
            {memoryUpdate.accepted ? "Memory updated" : "Memory not updated"}
          </div>
          {memoryUpdate.accepted ? (
            <ul className="space-y-1 text-sm text-slate-300">
              <li className="flex gap-2"><span className="text-emerald-400">✓</span> Incident retained</li>
              <li className="flex gap-2"><span className="text-emerald-400">✓</span> Recommendation retained</li>
              <li className="flex gap-2"><span className="text-emerald-400">✓</span> Outcome retained</li>
            </ul>
          ) : (
            <p className="text-sm text-[var(--color-text-muted)]">{memoryUpdate.reason}</p>
          )}
        </div>
      )}
    </div>
  );
}

export default function IncidentInvestigationPage() {
  const { id } = useParams();
  const incidentQ = useAsync(() => api.getIncident(id), [id]);

  const [agent, setAgent] = useState({ loading: true, error: null, data: null });
  const [acting, setActing] = useState(false);
  const [actResult, setActResult] = useState(null);
  const [actError, setActError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setAgent({ loading: true, error: null, data: null });
    setActResult(null);
    setActError(null);
    api.agentStart(id)
      .then((data) => { if (!cancelled) setAgent({ loading: false, error: null, data }); })
      .catch((error) => { if (!cancelled) setAgent({ loading: false, error, data: null }); });
    return () => { cancelled = true; };
  }, [id]);

  async function act(decision) {
    setActing(true);
    setActError(null);
    try {
      const result = await api.agentAct(id, { decision, fix: agent.data?.recommendation?.fix });
      setActResult(result);
    } catch (e) {
      setActError(e);
    } finally {
      setActing(false);
    }
  }

  const inc = incidentQ.data;
  const a = agent.data;
  const investigating = agent.loading;
  const alreadyCompleted = a && (a.status === "done" || a.status === "rejected");
  const finished = actResult || alreadyCompleted;

  return (
    <div className="space-y-5">
      <Link to="/incidents" className="text-xs text-[var(--color-text-faint)] hover:text-white">← Incidents</Link>

      <div>
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-xl font-semibold text-white">Incident Investigation</h1>
          {a?.recommendation && (
            <Badge color={riskMeta(a.recommendation.risk_tier).color} bg={riskMeta(a.recommendation.risk_tier).bg}>
              {riskMeta(a.recommendation.risk_tier).label}
            </Badge>
          )}
          {alreadyCompleted && (
            <Badge color="#4ade80" bg="rgba(34,197,94,0.12)">
              {a.status === "rejected" ? "Rejected" : "Resolved"}
            </Badge>
          )}
        </div>
        <p className="mt-1 text-sm text-[var(--color-text-muted)]">
          {inc ? `${inc.service} · ${inc.error_signature} · ${formatDate(inc.timestamp)}` : " "}
        </p>
      </div>

      {incidentQ.error && <ErrorBox error={incidentQ.error} onRetry={incidentQ.reload} />}
      {inc && <IncidentContext inc={inc} />}

      <Card title="OrbitAI Investigation">
        <ProcessSteps done={!investigating && !agent.error} extraStep={a?.courtroom_required ? "Courtroom convened" : undefined} />
        {investigating && <div className="mt-3"><Loading label="Agent is investigating…" /></div>}
      </Card>

      {agent.error && <ErrorBox error={agent.error} />}

      {a && inc && (
        <>
          <Card title="Possible Causes" subtitle="Derived from the incident's own recorded changes and factors — not the recommendation's evidence">
            <PotentialCauses incident={inc} />
          </Card>

          <Card title="Historical Memory" subtitle={`OrbitAI found ${a.similar_incidents?.length ?? 0} similar historical incident${a.similar_incidents?.length === 1 ? "" : "s"} in memory (${a.memory_results_count} candidates recalled)`}>
            <SimilarIncidentsList incidents={a.similar_incidents} />
          </Card>

          {a.recommendation ? (
            <Card
              title="Recommendation"
              subtitle="Cause confidence (above) and recommendation trust (below) are kept separate — trust is computed in code, never a raw LLM confidence"
              accent="#60a5fa"
            >
              <RecommendationBody rec={a.recommendation} gate={a.gate_decision} />
            </Card>
          ) : (
            <Card title="Recommendation">
              <p className="text-sm text-[var(--color-text-faint)]">No fixes recalled for this incident — novel combination, human decides.</p>
            </Card>
          )}

          {a.recommendation && (
            a.courtroom_result ? (
              <Card title="AI Courtroom" subtitle="Convened automatically — high risk, conflicting evidence, or low confidence">
                <CourtroomResult result={a.courtroom_result} />
              </Card>
            ) : (
              <Card title="AI Courtroom">
                <p className="text-sm text-[var(--color-text-faint)]">Courtroom not required — evidence confidence is sufficient.</p>
              </Card>
            )
          )}

          {a.recommendation && a.awaiting_human && !finished && (
            <Card title="Human Decision">
              <div className="flex flex-wrap items-center gap-3">
                <button
                  onClick={() => act("approve")}
                  disabled={acting}
                  className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-semibold text-white shadow-md shadow-emerald-950/40 hover:bg-emerald-500 disabled:opacity-50"
                >
                  {acting ? "Working…" : `Approve & Execute ${fixLabel(a.recommendation.fix)}`}
                </button>
                <button
                  onClick={() => act("reject")}
                  disabled={acting}
                  className="rounded-md border border-red-500/30 bg-red-500/10 px-4 py-2 text-sm font-semibold text-red-300 hover:bg-red-500/20 disabled:opacity-50"
                >
                  Reject
                </button>
              </div>
              {actError && <div className="mt-3 text-sm text-red-300">{actError.message}</div>}
            </Card>
          )}

          {actResult && (
            <Card title="Outcome">
              <Outcome
                status={actResult.status}
                executionResult={actResult.execution_result}
                observedOutcome={actResult.observed_outcome}
                memoryUpdate={actResult.memory_update}
                fix={a.recommendation?.fix}
              />
            </Card>
          )}

          {!actResult && alreadyCompleted && (
            <Card title="Outcome">
              <Outcome
                status={a.status}
                executionResult={a.execution_result}
                observedOutcome={a.observed_outcome}
                memoryUpdate={a.memory_update}
                humanAction={a.human_action}
                fix={a.recommendation?.fix}
              />
            </Card>
          )}
        </>
      )}
    </div>
  );
}
