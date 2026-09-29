export default function StatTile({ label, value, sub, subColor, accent, icon: Icon }) {
  const color = accent || "var(--color-brand-bright)";
  return (
    <div
      className="rounded-xl border bg-[var(--color-surface-1)]/70 p-4 shadow-lg shadow-black/20 transition-colors hover:bg-[var(--color-surface-1)]"
      style={{ borderColor: `${color}40` }}
    >
      <div className="flex items-center gap-3">
        {Icon && (
          <div
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full"
            style={{ color, backgroundColor: `${color}1f` }}
          >
            <Icon width={17} height={17} />
          </div>
        )}
        <div className="min-w-0 text-xs font-medium uppercase tracking-wide text-[var(--color-text-faint)]">{label}</div>
      </div>
      <div className="mt-2.5 text-3xl font-semibold text-white">{value}</div>
      {sub && <div className="mt-1 text-xs font-medium" style={{ color: subColor || "var(--color-text-muted)" }}>{sub}</div>}
    </div>
  );
}
