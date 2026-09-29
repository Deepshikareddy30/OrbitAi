import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { IconActivity, IconClipboard, IconClose, IconGrid, IconMenu } from "./icons.jsx";

const NAV = [
  { to: "/incidents", label: "Incidents", icon: IconGrid },
  { to: "/health", label: "AI Health", icon: IconActivity },
  { to: "/audit", label: "Audit Log", icon: IconClipboard },
];

function Brand() {
  return (
    <div className="flex items-center gap-2.5 px-1">
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-blue-500 to-indigo-600 text-sm font-bold text-white shadow-lg shadow-blue-950/50">
        OA
      </div>
      <div className="min-w-0">
        <div className="truncate text-sm font-semibold leading-tight text-white">OrbitAI</div>
        <div className="truncate text-[11px] leading-tight text-[var(--color-text-faint)]">AI Incident Response Agent</div>
      </div>
    </div>
  );
}

function NavList({ onNavigate }) {
  return (
    <nav className="flex flex-col gap-1">
      {NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          onClick={onNavigate}
          className={({ isActive }) =>
            `flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
              isActive
                ? "bg-blue-600 text-white shadow-md shadow-blue-950/40"
                : "text-[var(--color-text-muted)] hover:bg-white/5 hover:text-white"
            }`
          }
        >
          {({ isActive }) => (
            <>
              <item.icon className="shrink-0" />
              <span className="flex-1">{item.label}</span>
              {isActive && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-white/70" />}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );
}

function EnvCard() {
  return (
    <div className="rounded-lg border border-amber-500/25 bg-amber-500/10 p-3">
      <div className="flex items-center gap-2 text-xs font-semibold text-amber-400">
        <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
        Simulated environment
      </div>
      <p className="mt-1 text-[11px] leading-snug text-amber-200/70">
        All incidents, outcomes and history are synthetic. Nothing here touches real infrastructure.
      </p>
    </div>
  );
}

export default function Layout() {
  const [mobileOpen, setMobileOpen] = useState(false);

  return (
    <div className="min-h-screen bg-[var(--color-bg)] text-[var(--color-text)] lg:flex">
      {/* Mobile top bar */}
      <div className="sticky top-0 z-30 flex items-center justify-between border-b border-[var(--color-border-soft)] bg-[var(--color-surface-1)]/95 px-4 py-3 backdrop-blur lg:hidden"
          style={{ paddingTop: "max(0.75rem, env(safe-area-inset-top, 0px))" }}>
        <Brand />
        <button onClick={() => setMobileOpen(true)} aria-label="Open menu"
               className="rounded-md p-1.5 text-[var(--color-text-muted)] hover:bg-white/5 hover:text-white">
          <IconMenu />
        </button>
      </div>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setMobileOpen(false)} />
          <div className="absolute inset-y-0 left-0 flex w-72 flex-col gap-6 border-r border-[var(--color-border-soft)] bg-[var(--color-surface-1)] p-4"
              style={{ paddingTop: "max(1rem, env(safe-area-inset-top, 0px))" }}>
            <div className="flex items-center justify-between">
              <Brand />
              <button onClick={() => setMobileOpen(false)} aria-label="Close menu"
                     className="rounded-md p-1.5 text-[var(--color-text-muted)] hover:bg-white/5 hover:text-white">
                <IconClose />
              </button>
            </div>
            <NavList onNavigate={() => setMobileOpen(false)} />
            <div className="mt-auto">
              <EnvCard />
            </div>
          </div>
        </div>
      )}

      {/* Desktop sidebar */}
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col gap-6 border-r border-[var(--color-border-soft)] bg-[var(--color-surface-1)]/60 p-4 lg:flex">
        <Brand />
        <NavList />
        <div className="mt-auto flex flex-col gap-3">
          <EnvCard />
          <p className="px-1 text-[10px] text-[var(--color-text-faint)]">
            docs/SPEC.md is the source of truth
          </p>
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        <main className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
