export default function Card({ title, subtitle, right, children, className = "", accent }) {
  return (
    <div
      className={`rounded-xl border border-[var(--color-border-soft)] bg-[var(--color-surface-1)]/70 shadow-lg shadow-black/20 backdrop-blur-sm ${className}`}
      style={accent ? { borderLeft: `3px solid ${accent}` } : undefined}
    >
      {(title || right) && (
        <div className="flex items-center justify-between border-b border-[var(--color-border-soft)] px-4 py-3 sm:px-5">
          <div className="min-w-0">
            {title && <h3 className="truncate text-sm font-semibold text-white">{title}</h3>}
            {subtitle && <p className="mt-0.5 truncate text-xs text-[var(--color-text-faint)]">{subtitle}</p>}
          </div>
          {right && <div className="shrink-0">{right}</div>}
        </div>
      )}
      <div className="p-4 sm:p-5">{children}</div>
    </div>
  );
}
