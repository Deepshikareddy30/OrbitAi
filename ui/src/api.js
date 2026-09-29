const BASE = import.meta.env.VITE_API_BASE || "/api";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || JSON.stringify(body);
    } catch {
      /* ignore parse failure, keep statusText */
    }
    throw new Error(`${res.status} ${detail}`);
  }
  return res.status === 204 ? null : res.json();
}

export const api = {
  health: () => request("/health"),
  fixes: () => request("/fixes"),
  gateConfig: () => request("/gate/config"),
  listIncidents: (split, { q, limit, offset } = {}) => {
    const params = new URLSearchParams();
    if (split) params.set("split", split);
    if (q) params.set("q", q);
    if (limit) params.set("limit", String(limit));
    if (offset) params.set("offset", String(offset));
    const qs = params.toString();
    return request(`/incidents${qs ? `?${qs}` : ""}`);
  },
  getIncident: (id) => request(`/incidents/${id}`),
  getRecommendation: (id) => request(`/incidents/${id}/recommendation`),
  executeFix: (id, body) =>
    request(`/incidents/${id}/execute`, { method: "POST", body: JSON.stringify(body) }),
  poison: (id, body) =>
    request(`/incidents/${id}/poison`, { method: "POST", body: JSON.stringify(body) }),
  demoIncidents: () => request("/demo/incidents"),
  demoReset: () => request("/demo/reset", { method: "POST" }),
  weightVersions: () => request("/weights/versions"),
  weightVersion: (v) => request(`/weights/${v}`),
  audit: (event) => request(`/audit${event ? `?event=${event}` : ""}`),
  evalResults: () => request("/eval/results"),
  courtroom: (id, body = {}) =>
    request(`/incidents/${id}/courtroom`, { method: "POST", body: JSON.stringify(body) }),

  // Agent (agent/graph.py) - the stateful LangGraph orchestration.
  agentStart: (id) => request(`/agent/incidents/${id}/start`, { method: "POST" }),
  agentAct: (id, body) =>
    request(`/agent/incidents/${id}/act`, { method: "POST", body: JSON.stringify(body) }),
  // Read-only checkpoint peek - does NOT trigger a run, unlike agentStart. Used to
  // tell whether an incident is untouched/in-progress/done without paying for one.
  agentState: (id) =>
    request(`/agent/incidents/${id}/state`).catch((e) => {
      if (String(e.message).startsWith("404")) return null;
      throw e;
    }),
};
