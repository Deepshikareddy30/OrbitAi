import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api.js";
import { useAsync } from "../lib/useAsync.js";
import { Loading, ErrorBox, EmptyState } from "../components/Status.jsx";
import Card from "../components/Card.jsx";
import Badge from "../components/Badge.jsx";
import StatTile from "../components/StatTile.jsx";
import { IconActivity, IconClipboard, IconGrid, IconSearch, IconShield } from "../components/icons.jsx";
import { formatDate, riskMeta } from "../lib/format.js";

const PAGE_SIZE = 25;
// Small enough to transfer in one shot for stat tiles at this dataset's size (~300);
// revisit with a dedicated /incidents/stats endpoint if the dataset grows a lot.
const STATS_LIMIT = 2000;
const SEARCH_DEBOUNCE_MS = 250;
const FLAGSHIP_ID = "DEMO-FLAGSHIP";

const SPLIT_TABS = [
  { value: undefined, label: "All" },
  { value: "train", label: "Train (memory)" },
  { value: "held_out", label: "Held-out" },
];

const SPLIT_META = {
  train: { label: "In memory", color: "#60a5fa", bg: "rgba(59,130,246,0.12)" },
  held_out: { label: "Held-out", color: "#22d3ee", bg: "rgba(34,211,238,0.12)" },
  demo: { label: "Demo", color: "#fbbf24", bg: "rgba(251,191,36,0.12)" },
};

async function loadActiveIncident() {
  const demo = await api.demoIncidents();
  const inc = demo.find((d) => d.id === FLAGSHIP_ID) || demo[0];
  if (!inc) return { inc: null };
  const [rec, agentState] = await Promise.all([
    api.getRecommendation(inc.id).catch(() => null),
    api.agentState(inc.id),
  ]);
  const top = rec?.ranked_fixes?.[0]?.evidence ?? null;
  let status = "new";
  if (agentState) {
    status = agentState.awaiting_human ? "in_progress" : agentState.state?.status === "rejected" ? "rejected" : "done";
  }
  return { inc, top, status };
}

function ActiveIncidentCard({ inc, top }) {
  const risk = top ? riskMeta(top.risk_tier) : riskMeta("medium");
  return (
    <Card accent={risk.color}>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-lg font-semibold text-white">{inc.service}</span>
            <Badge color={risk.color} bg={risk.bg}>{risk.label}</Badge>
          </div>
          <div className="mt-1 font-mono text-sm text-[var(--color-text-muted)]">{inc.error_signature}</div>
          <div className="mt-1 text-xs text-[var(--color-text-faint)]">Detected {formatDate(inc.timestamp)}</div>
        </div>
        <Link
          to={`/incidents/${inc.id}`}
          className="inline-flex shrink-0 items-center gap-2 rounded-md bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-md shadow-blue-950/40 hover:bg-blue-500"
        >
          Investigate →
        </Link>
      </div>
    </Card>
  );
}

function ActiveIncidentInProgress({ inc, top }) {
  const risk = top ? riskMeta(top.risk_tier) : riskMeta("medium");
  return (
    <Card accent={risk.color}>
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-lg font-semibold text-white">{inc.service}</span>
            <Badge color={risk.color} bg={risk.bg}>{risk.label}</Badge>
            <Badge color="#fbbf24" bg="rgba(251,191,36,0.12)">Awaiting your decision</Badge>
          </div>
          <div className="mt-1 font-mono text-sm text-[var(--color-text-muted)]">{inc.error_signature}</div>
        </div>
        <Link
          to={`/incidents/${inc.id}`}
          className="inline-flex shrink-0 items-center gap-2 rounded-md bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white shadow-md shadow-blue-950/40 hover:bg-blue-500"
        >
          Continue →
        </Link>
      </div>
    </Card>
  );
}

function ActiveIncidentsSection() {
  const { data, error, loading, reload } = useAsync(loadActiveIncident, []);

  if (loading) return <Card title="Active Incidents"><Loading label="Checking for active incidents…" /></Card>;
  if (error) return <Card title="Active Incidents"><ErrorBox error={error} onRetry={reload} /></Card>;
  if (!data?.inc) return null;

  const { inc, top, status } = data;

  return (
    <div>
      <h2 className="mb-2.5 text-sm font-semibold uppercase tracking-wide text-[var(--color-text-faint)]">Active Incidents</h2>
      {status === "new" && <ActiveIncidentCard inc={inc} top={top} />}
      {status === "in_progress" && <ActiveIncidentInProgress inc={inc} top={top} />}
      {(status === "done" || status === "rejected") && (
        <Card>
          <p className="text-sm text-[var(--color-text-muted)]">
            No active incidents — all clear. See the{" "}
            <Link to="/audit" className="text-blue-400 hover:text-blue-300 hover:underline">Audit Log</Link>{" "}
            for what OrbitAI just handled.
          </p>
        </Card>
      )}
    </div>
  );
}

export default function IncidentListPage() {
  const [split, setSplit] = useState(undefined);
  const [page, setPage] = useState(0);
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    const id = setTimeout(() => setSearch(searchInput.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(id);
  }, [searchInput]);

  function selectSplit(value) {
    setSplit(value);
    setPage(0);
  }

  useEffect(() => setPage(0), [search]);

  const { data, error, loading, reload } = useAsync(
    () => api.listIncidents(split, { q: search || undefined, limit: PAGE_SIZE, offset: page * PAGE_SIZE }),
    [split, search, page],
  );
  const allQ = useAsync(() => api.listIncidents(undefined, { limit: STATS_LIMIT }), []);

  const stats = useMemo(() => {
    const all = allQ.data?.incidents;
    if (!all) return null;
    const train = all.filter((i) => i.split === "train").length;
    const heldOut = all.filter((i) => i.split === "held_out").length;
    const attempts = all.reduce((s, i) => s + i.n_attempts, 0);
    return { total: allQ.data.count, train, heldOut, attempts };
  }, [allQ.data]);

  const totalPages = data ? Math.max(1, Math.ceil(data.count / PAGE_SIZE)) : 1;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-white">Incidents</h1>
        <p className="mt-1.5 text-sm text-[var(--color-text-muted)]">
          Active incidents awaiting investigation, plus the full historical record.
        </p>
      </div>

      <ActiveIncidentsSection />

      <div>
        <h2 className="mb-2.5 text-sm font-semibold uppercase tracking-wide text-[var(--color-text-faint)]">All Incidents</h2>

        {stats && (
          <div className="mb-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile label="Total incidents" value={stats.total} icon={IconGrid} />
            <StatTile label="In memory" value={stats.train} sub="train split" subColor="#60a5fa" icon={IconShield} accent="#60a5fa" />
            <StatTile label="Held-out" value={stats.heldOut} sub="evaluation split" subColor="#22d3ee" icon={IconActivity} accent="#22d3ee" />
            <StatTile label="Total attempts" value={stats.attempts} icon={IconClipboard} />
          </div>
        )}

        <div className="mb-4 flex flex-wrap items-center gap-2.5">
          <div className="relative flex-1 min-w-[220px]">
            <IconSearch width={16} height={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-[var(--color-text-faint)]" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Search by incident ID, service, or error signature…"
              className="w-full rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-surface-1)]/70 py-2.5 pl-9 pr-3 text-sm text-white placeholder:text-[var(--color-text-faint)] outline-none transition-colors focus:border-blue-500/50 focus:bg-[var(--color-surface-1)]"
            />
          </div>
          <div className="flex gap-1 rounded-lg border border-[var(--color-border-soft)] bg-[var(--color-surface-1)]/70 p-1">
            {SPLIT_TABS.map((t) => (
              <button
                key={t.label}
                onClick={() => selectSplit(t.value)}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors ${
                  split === t.value ? "bg-blue-600 text-white" : "text-[var(--color-text-muted)] hover:bg-white/5 hover:text-white"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        </div>

        {loading && <Loading label="Loading incidents…" />}
        {error && <ErrorBox error={error} onRetry={reload} />}
        {data && data.incidents.length === 0 && (
          <EmptyState>{search ? `No incidents match "${search}".` : "No incidents in this view."}</EmptyState>
        )}

        {data && data.incidents.length > 0 && (
          <div className="overflow-hidden rounded-xl border border-[var(--color-border-soft)] bg-[var(--color-surface-1)]/70 shadow-lg shadow-black/20">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[680px] text-left text-sm">
                <thead className="border-b border-[var(--color-border-soft)] bg-black/25 text-xs uppercase tracking-wide text-[var(--color-text-faint)]">
                  <tr>
                    <th className="px-4 py-3 font-medium">Incident</th>
                    <th className="px-4 py-3 font-medium">Service</th>
                    <th className="px-4 py-3 font-medium">Environment</th>
                    <th className="px-4 py-3 font-medium">Signature</th>
                    <th className="px-4 py-3 font-medium">When</th>
                    <th className="px-4 py-3 font-medium">Attempts</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.incidents.map((inc) => {
                    const meta = SPLIT_META[inc.split] || SPLIT_META.train;
                    return (
                      <tr key={inc.id} className="border-b border-[var(--color-border-soft)] last:border-0 hover:bg-white/[0.03]">
                        <td className="px-4 py-3">
                          <Link to={`/incidents/${inc.id}`} className="font-medium text-blue-400 hover:text-blue-300 hover:underline">
                            {inc.id}
                          </Link>
                        </td>
                        <td className="px-4 py-3 text-slate-200">{inc.service}</td>
                        <td className="px-4 py-3 text-[var(--color-text-muted)]">{inc.environment}</td>
                        <td className="px-4 py-3 font-mono text-xs text-[var(--color-text-muted)]">{inc.error_signature}</td>
                        <td className="px-4 py-3 text-[var(--color-text-muted)]">{formatDate(inc.timestamp)}</td>
                        <td className="px-4 py-3 text-[var(--color-text-muted)]">{inc.n_attempts}</td>
                        <td className="px-4 py-3">
                          <Badge color={meta.color} bg={meta.bg}>{meta.label}</Badge>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--color-border-soft)] px-4 py-2.5 text-xs text-[var(--color-text-faint)]">
              <span>
                Showing {page * PAGE_SIZE + 1}–{Math.min(data.count, page * PAGE_SIZE + data.incidents.length)} of {data.count}
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={page === 0}
                  className="rounded-md border border-[var(--color-border-soft)] px-2.5 py-1 font-medium text-[var(--color-text-muted)] hover:bg-white/5 hover:text-white disabled:opacity-30"
                >
                  Prev
                </button>
                <span>Page {page + 1} of {totalPages}</span>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={page >= totalPages - 1}
                  className="rounded-md border border-[var(--color-border-soft)] px-2.5 py-1 font-medium text-[var(--color-text-muted)] hover:bg-white/5 hover:text-white disabled:opacity-30"
                >
                  Next
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
