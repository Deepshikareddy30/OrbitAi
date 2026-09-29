import { Navigate, Route, Routes, useParams } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import IncidentListPage from "./pages/IncidentListPage.jsx";
import IncidentInvestigationPage from "./pages/IncidentInvestigationPage.jsx";
import DemoPage from "./pages/DemoPage.jsx";
import GatePage from "./pages/GatePage.jsx";
import AIHealthPage from "./pages/AIHealthPage.jsx";
import AuditLogPage from "./pages/AuditLogPage.jsx";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Navigate to="/incidents" replace />} />
        <Route path="/incidents" element={<IncidentListPage />} />
        {/* The ONE canonical incident-detail experience - incident context, the full
           LangGraph agent investigation, and (once acted on) its outcome/memory-update
           replay, all in one place. See docs/DECISIONS.md AGENT5. */}
        <Route path="/incidents/:id" element={<IncidentInvestigationPage />} />
        <Route path="/incidents/:id/respond" element={<RedirectToIncident />} />
        {/* Dev/testing only - the A-E scenario picker + poisoning-guard playground,
           and the Adaptive Gate reference page. Not in the primary nav: the judge-
           facing flow is Incidents -> investigate -> Audit Log. Both still fully
           working, still reachable by URL. */}
        <Route path="/demo" element={<DemoPage />} />
        <Route path="/gate" element={<GatePage />} />
        <Route path="/health" element={<AIHealthPage />} />
        <Route path="/audit" element={<AuditLogPage />} />
      </Route>
    </Routes>
  );
}

function RedirectToIncident() {
  const { id } = useParams();
  return <Navigate to={`/incidents/${id}`} replace />;
}
