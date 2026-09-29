import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useAsync } from "../lib/useAsync.js";
import { Loading, ErrorBox, EmptyState } from "../components/Status.jsx";
import Card from "../components/Card.jsx";
import Badge from "../components/Badge.jsx";
import { fixLabel, formatTrust, outcomeColor } from "../lib/format.js";

// Humanized labels for the agent's own lifecycle events (agent/graph.py's
// audit_events). Falls back to the raw event name for anything else (mostly
// pre-agent engine events - recommendation_verified, weights_refit, etc).
const EVENT_LABELS = {
  incident_context_gathered: () => "Incident context gathered",
  memory_retrieved: (e) => `Historical memory retrieved (${e.count} candidate${e.count === 1 ? "" : "s"})`,
  candidate_actions_generated: (e) => `${e.n} candidate action${e.n === 1 ? "" : "s"} generated`,
  recommendation_selected: (e) => `Recommendation selected: ${fixLabel(e.fix)} (T=${formatTrust(e.trust)})`,
  trust_calculated: (e) => `Trust calculated: ${formatTrust(e.trust)}`,
  courtroom_convened: (e) => `Courtroom convened — trust ${formatTrust(e.base_trust)} → ${formatTrust(e.final_trust)}`,
  human_action_received: (e) => `Human ${e.decision === "approve" ? "approved" : "rejected"} the recommendation`,
  action_executed: (e) => `${fixLabel(e.fix)} executed`,
  outcome_observed: (e) => `Outcome verified: ${e.outcome}`,
  memory_updated: (e) => (e.accepted ? "Hindsight memory updated" : "Memory not updated (unverified)"),
  action_rejected: (e) => `Rejected${e.reason ? ` — ${e.reason}` : ""}`,
  no_recommendation: () => "No recommendation — novel incident, human decides",
};

function eventLabel(e) {
  const fn = EVENT_LABELS[e.event];
  return fn ? fn(e) : e.event;
}

function shortTime(ts) {
  if (!ts) return "";
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

/** One investigation run can leave several checkpointed executions of the same node
 * behind it (e.g. a revisit before the idempotency fix - docs/DECISIONS.md AGENT5).
 * For display, collapse to the LAST occurrence of each event name so the timeline
 * reads as one coherent run instead of a repeated one; nothing is deleted from the
 * underlying log, this only affects what's rendered. */
function dedupeTimeline(events) {
  const lastByName = new Map();
  for (const e of events) lastByName.set(e.event, e);
  return [...lastByName.values()].sort((a, b) => (a.ts || "").localeCompare(b.ts || ""));
}

function groupByIncident(events) {
  const groups = new Map();
  const system = [];
  for (const e of events) {
    if (!e.incident_id) {
      system.push(e);
      continue;
    }
    if (!groups.has(e.incident_id)) groups.set(e.incident_id, []);
    groups.get(e.incident_id).push(e);
  }
  const incidents = [...groups.entries()].map(([incidentId, raw]) => {
    const timeline = dedupeTimeline(raw);
    const byName = Object.fromEntries(timeline.map((e) => [e.event, e]));
    const rejected = !!byName.action_rejected;
    const outcome = byName.outcome_observed?.outcome;
    const status = rejected ? "rejected" : outcome ? "done" : byName.human_action_received ? "in_progress" : "investigating";
    return {
      incidentId,
      timeline,
      fix: byName.recommendation_selected?.fix,
      trust: byName.courtroom_convened?.final_trust ?? byName.recommendation_selected?.trust,
      outcome,
      rejected,
      status,
      lastTs: timeline[timeline.length - 1]?.ts,
    };
  });
  incidents.sort((a, b) => (b.lastTs || "").localeCompare(a.lastTs || ""));
  return { incidents, system };
}

async function loadGrouped() {
  const { events } = await api.audit();
  const { incidents, system } = groupByIncident(events);
  const details = await Promise.all(
    incidents.map((g) => api.getIncident(g.incidentId).catch(() => null)),
  );
  return { incidents: incidents.map((g, i) => ({ ...g, incident: details[i] })), system };
}

const STATUS_META = {
  done: { label: "Resolved", color: "#4ade80", bg: "rgba(34,197,94,0.12)" },
  rejected: { label: "Rejected", color: "#f87171", bg: "rgba(248,113,113,0.12)" },
  in_progress: { label: "Awaiting decision", color: "#fbbf24", bg: "rgba(251,191,36,0.12)" },
  investigating: { label: "Investigating", color: "#60a5fa", bg: "rgba(59,130,246,0.12)" },
};

function IncidentRecord({ g }) {
  const [open, setOpen] = useState(false);
  const meta = STATUS_META[g.status];
  return (
    <div className="rounded-xl border border-[var(--color-border-soft)] bg-[var(--color-surface-1)]/70 shadow-lg shadow-black/20">
      <button onClick={() => setOpen((o) => !o)} className="flex w-full flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 text-left">
        <Link
          to={`/incidents/${g.incidentId}`}
          onClick={(e) => e.stopPropagation()}
          className="font-medium text-blue-400 hover:text-blue-300 hover:underline"
        >
          {g.incidentId}
        </Link>
        {g.incident && <span className="text-sm text-slate-300">{g.incident.service}</span>}
        {g.fix && <span className="text-sm text-[var(--color-text-muted)]">{fixLabel(g.fix)}</span>}
        <span className="ml-auto flex items-center gap-3">
          {g.outcome && <span style={{ color: outcomeColor(g.outcome) }} className="text-xs font-semibold">{g.outcome}</span>}
          {g.trust != null && <span className="mono text-sm text-slate-300">T={formatTrust(g.trust)}</span>}
          <Badge color={meta.color} bg={meta.bg}>{meta.label}</Badge>
          <span className="text-[var(--color-text-faint)]">{open ? "−" : "+"}</span>
        </span>
      </button>
      {open && (
        <div className="border-t border-[var(--color-border-soft)] px-4 py-3.5">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-[var(--color-text-faint)]">Timeline</div>
          <ul className="space-y-1.5">
            {g.timeline.map((e, i) => (
              <li key={i} className="flex items-baseline gap-3 text-sm">
                <span className="mono w-12 shrink-0 text-xs text-[var(--color-text-faint)]">{shortTime(e.ts)}</span>
                <span className="text-slate-300">{eventLabel(e)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function AuditLogPage() {
  const { data, error, loading, reload } = useAsync(loadGrouped, []);
  const [showSystem, setShowSystem] = useState(false);

  const systemPreview = useMemo(() => data?.system.slice(-20).reverse() ?? [], [data]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-white">Audit Log</h1>
          <p className="mt-1 text-sm text-[var(--color-text-muted)]">
            The permanent historical record — every incident OrbitAI has investigated, what it recommended, and what happened.
          </p>
        </div>
        <button onClick={reload} className="rounded-md border border-[var(--color-border-soft)] bg-[var(--color-surface-1)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-muted)] hover:bg-white/5 hover:text-white">
          Refresh
        </button>
      </div>

      {loading && <Loading />}
      {error && <ErrorBox error={error} onRetry={reload} />}
      {data && data.incidents.length === 0 && <EmptyState>No incidents investigated yet — open one from Incidents to generate a record.</EmptyState>}

      {data && data.incidents.length > 0 && (
        <div className="space-y-2.5">
          {data.incidents.map((g) => <IncidentRecord key={g.incidentId} g={g} />)}
        </div>
      )}

      {data && data.system.length > 0 && (
        <div className="pt-2">
          <button
            onClick={() => setShowSystem((s) => !s)}
            className="text-xs font-medium text-[var(--color-text-faint)] hover:text-[var(--color-text-muted)]"
          >
            {showSystem ? "Hide" : "Show"} system events ({data.system.length})
          </button>
          {showSystem && (
            <ul className="mt-2 space-y-1 rounded-lg border border-[var(--color-border-soft)] bg-black/20 p-3">
              {systemPreview.map((e, i) => (
                <li key={i} className="flex flex-wrap items-baseline gap-2 text-xs text-[var(--color-text-faint)]">
                  <span className="mono">{shortTime(e.ts)}</span>
                  <span>{e.event}</span>
                  <span className="text-[var(--color-text-faint)]/70">
                    {Object.entries(e).filter(([k]) => !["event", "ts", "incident_id"].includes(k)).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(" ")}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
