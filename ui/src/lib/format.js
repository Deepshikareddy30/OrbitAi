export const VERDICT_META = {
  agree_trust: { label: "Trust this fix", color: "#4ade80", bg: "rgba(34,197,94,0.12)", border: "rgba(34,197,94,0.35)" },
  agree_dont_trust: { label: "Don't trust this fix", color: "#f87171", bg: "rgba(248,113,113,0.12)", border: "rgba(248,113,113,0.35)" },
  conflict: { label: "Conflict — escalate", color: "#fbbf24", bg: "rgba(251,191,36,0.12)", border: "rgba(251,191,36,0.35)" },
  no_evidence: { label: "No evidence", color: "#94a3b8", bg: "rgba(148,163,184,0.12)", border: "rgba(148,163,184,0.3)" },
};

export function verdictMeta(verdict) {
  return VERDICT_META[verdict] || VERDICT_META.no_evidence;
}

export const RISK_META = {
  low: { label: "Low risk", color: "#4ade80", bg: "rgba(34,197,94,0.12)" },
  medium: { label: "Medium risk", color: "#fbbf24", bg: "rgba(251,191,36,0.12)" },
  high: { label: "High risk", color: "#f87171", bg: "rgba(248,113,113,0.12)" },
};

export function riskMeta(tier) {
  return RISK_META[tier] || RISK_META.medium;
}

export const GATE_META = {
  auto_run: { label: "Auto-run", detail: "Notify on-call, no approval needed" },
  one_click: { label: "One-click approval", detail: "On-call must approve" },
  escalate_ic: { label: "Escalate to IC", detail: "Incident commander must approve" },
  two_person: { label: "Two-person approval", detail: "Two people must approve" },
  break_glass: { label: "Break glass", detail: "Emergency override — requires post-incident review" },
};

export function gateMeta(action) {
  return GATE_META[action] || { label: action, detail: "" };
}

export function formatPct(x, digits = 0) {
  if (x === null || x === undefined) return "–";
  return `${(x * 100).toFixed(digits)}%`;
}

export function formatTrust(t) {
  if (t === null || t === undefined) return "–";
  return t.toFixed(2);
}

export function formatDate(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

export function fixLabel(fix) {
  return fix.replace(/_/g, " ");
}

export function outcomeColor(outcome) {
  if (outcome === "resolved") return "#4ade80";
  if (outcome === "recurred") return "#fbbf24";
  return "#f87171";
}
