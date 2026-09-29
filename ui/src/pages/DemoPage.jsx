import { useState } from "react";
import { api } from "../api.js";
import { useAsync } from "../lib/useAsync.js";
import { Loading, ErrorBox } from "../components/Status.jsx";
import Card from "../components/Card.jsx";
import Badge from "../components/Badge.jsx";
import TrustLedger from "../components/TrustLedger.jsx";

const SCENARIO_NOTES = {
  A: "Close match to many past passes of one fix, no similar failures.",
  B: "Close match to past failures of the obvious fix — a different fix should win.",
  C: "Look-alike trap: symptoms match past memory-leak restarts that passed, but a deploy just before matches past restarts that failed.",
  D: "Novel: this service/fault combination was withheld from training entirely.",
  E: "Medium-risk fix with genuinely borderline trust.",
};

function ScenarioCard({ demo, onSelect, selected }) {
  const key = demo.id.split("-")[1];
  return (
    <button
      onClick={() => onSelect(demo.id)}
      className={`w-full rounded-lg border p-3 text-left transition-colors ${
        selected
          ? "border-blue-500/50 bg-blue-500/10"
          : "border-[var(--color-border-soft)] bg-[var(--color-surface-1)]/70 hover:bg-white/[0.04]"
      }`}
    >
      <div className="flex items-center gap-2">
        <Badge color="#60a5fa" bg="rgba(59,130,246,0.12)">{key}</Badge>
        <span className="truncate font-medium text-white">{demo.service}</span>
      </div>
      <div className="mt-1 truncate font-mono text-xs text-[var(--color-text-faint)]">{demo.error_signature}</div>
      <p className="mt-1.5 text-xs text-[var(--color-text-muted)]">{SCENARIO_NOTES[key]}</p>
    </button>
  );
}

export default function DemoPage() {
  const demoQ = useAsync(() => api.demoIncidents(), []);
  const [selected, setSelected] = useState(null);
  const recQ = useAsync(() => (selected ? api.getRecommendation(selected) : Promise.resolve(null)), [selected]);
  const [executing, setExecuting] = useState(null);
  const [execResult, setExecResult] = useState(null);
  const [resetting, setResetting] = useState(false);

  async function handleExecute(fix) {
    setExecuting(fix);
    setExecResult(null);
    try {
      const result = await api.executeFix(selected, { fix });
      setExecResult(result);
      recQ.reload();
    } catch (e) {
      setExecResult({ error: e.message });
    } finally {
      setExecuting(null);
    }
  }

  async function handleReset() {
    setResetting(true);
    try {
      await api.demoReset();
      setSelected(null);
      setExecResult(null);
      demoQ.reload();
    } finally {
      setResetting(false);
    }
  }

  if (demoQ.loading) return <Loading label="Loading demo scenarios…" />;
  if (demoQ.error) return <ErrorBox error={demoQ.error} onRetry={demoQ.reload} />;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-white">Demo Walkthrough</h1>
          <p className="mt-1 text-sm text-[var(--color-text-muted)]">
            Five pre-generated incidents (A–E), none in training. Walk through each to see the evidence, then
            execute A and C to watch the weights update.
          </p>
        </div>
        <button
          onClick={handleReset}
          disabled={resetting}
          className="rounded-md border border-[var(--color-border-soft)] bg-[var(--color-surface-1)] px-3 py-1.5 text-xs font-medium text-[var(--color-text-muted)] hover:bg-white/5 hover:text-white disabled:opacity-50"
        >
          {resetting ? "Resetting…" : "Reset demo"}
        </button>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-5">
        {demoQ.data.map((d) => (
          <ScenarioCard key={d.id} demo={d} selected={selected === d.id} onSelect={setSelected} />
        ))}
      </div>

      {selected && (
        <Card title={selected} subtitle="Recalled evidence and recommendation for this scenario">
          {recQ.loading && <Loading />}
          {recQ.error && <ErrorBox error={recQ.error} onRetry={recQ.reload} />}
          {recQ.data && (
            <>
              <div className="mb-3 text-xs text-[var(--color-text-faint)]">
                {recQ.data.n_candidates} recalled cases
              </div>
              {recQ.data.ranked_fixes.length === 0 ? (
                <div className="rounded-md border border-[var(--color-border-soft)] bg-black/20 px-3 py-4 text-sm text-[var(--color-text-muted)]">
                  No fixes recalled — this is exactly what "novel incident, human decides" looks like.
                </div>
              ) : (
                <TrustLedger rankedFixes={recQ.data.ranked_fixes} onExecute={handleExecute} executing={executing} />
              )}
            </>
          )}
        </Card>
      )}

      {execResult && (
        <div className={`rounded-lg border px-4 py-3 text-sm ${execResult.error ? "border-red-500/25 bg-red-500/10 text-red-300" : "border-emerald-500/25 bg-emerald-500/10 text-emerald-200"}`}>
          {execResult.error ? (
            `Execution failed: ${execResult.error}`
          ) : (
            <>
              Executed <span className="font-medium">{execResult.fix.replace(/_/g, " ")}</span>: outcome{" "}
              <span className="font-medium">{execResult.outcome}</span>
              {execResult.accepted
                ? ` — verified and retained. The next similar incident's score just moved.`
                : ` — ${execResult.reason}`}
            </>
          )}
        </div>
      )}

      <Card title="Poisoning guard" subtitle="A fabricated 'always works' claim, submitted unverified/unauthorized">
        <PoisonDemo selected={selected} />
      </Card>
    </div>
  );
}

function PoisonDemo({ selected }) {
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!selected) return;
    setBusy(true);
    try {
      const r = await api.poison(selected, {
        fix: "db_failover", outcome: "resolved", writer: "anonymous-script", authorized: false, verified: false,
      });
      setResult(r);
    } finally {
      setBusy(false);
    }
  }

  if (!selected) {
    return <div className="text-sm text-[var(--color-text-faint)]">Select a scenario above to try submitting a poisoned claim against it.</div>;
  }

  return (
    <div>
      <p className="text-sm text-[var(--color-text-muted)]">
        Submit a claim that <span className="font-mono text-slate-300">db_failover</span> "always works" on <span className="font-medium text-white">{selected}</span>,
        from an unauthorized writer with an unverified outcome.
      </p>
      <button
        onClick={submit}
        disabled={busy}
        className="mt-3 rounded-md bg-slate-700 px-3.5 py-2 text-xs font-semibold text-white hover:bg-slate-600 disabled:opacity-50"
      >
        {busy ? "Submitting…" : "Submit poisoned claim"}
      </button>
      {result && (
        <div className="mt-3 rounded-md border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
          Stored in memory, but <span className="font-semibold text-amber-100">{result.accepted ? "accepted (unexpected!)" : "blocked"}</span>:{" "}
          {result.reason}. It will never influence the Trust Ledger's math.
        </div>
      )}
    </div>
  );
}
