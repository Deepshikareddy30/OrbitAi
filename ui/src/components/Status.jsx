export function Loading({ label = "Loading…" }) {
  return (
    <div className="flex items-center gap-2 py-8 text-sm text-[var(--color-text-faint)]">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/10 border-t-blue-400" />
      {label}
    </div>
  );
}

export function ErrorBox({ error, onRetry }) {
  return (
    <div className="rounded-lg border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm text-red-300">
      <div className="font-medium text-red-200">Something went wrong</div>
      <div className="mt-1 text-red-300/80">{error?.message || String(error)}</div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="mt-2 rounded-md border border-red-500/30 bg-red-500/10 px-2.5 py-1 text-xs font-medium text-red-200 hover:bg-red-500/20"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({ children }) {
  return <div className="py-8 text-center text-sm text-[var(--color-text-faint)]">{children}</div>;
}
