export default function Badge({ color, bg, border, children, className = "" }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium ${className}`}
      style={{ color, backgroundColor: bg, border: `1px solid ${border || `${color}40`}` }}
    >
      {children}
    </span>
  );
}
