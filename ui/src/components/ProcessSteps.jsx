import { useEffect, useState } from "react";

const STEPS = [
  "Incident context gathered",
  "Historical memory retrieved",
  "Similar incidents analyzed",
  "Candidate actions generated",
  "Trust evaluated",
];

/** Reveals steps in a quick stagger once `done` flips true - not a fake long loading
 * animation, just a beat so the pipeline reads as real stages, not a single opaque call. */
export default function ProcessSteps({ done, extraStep }) {
  const [revealed, setRevealed] = useState(0);
  const steps = extraStep ? [...STEPS, extraStep] : STEPS;

  useEffect(() => {
    if (!done) {
      setRevealed(0);
      return;
    }
    let i = 0;
    const id = setInterval(() => {
      i += 1;
      setRevealed(i);
      if (i >= steps.length) clearInterval(id);
    }, 120);
    return () => clearInterval(id);
  }, [done, steps.length]);

  return (
    <ul className="space-y-1.5">
      {steps.map((label, i) => (
        <li key={label} className="flex items-center gap-2 text-sm">
          {i < revealed ? (
            <span className="text-emerald-400">●</span>
          ) : (
            <span className="h-3 w-3 animate-pulse rounded-full border border-white/15" />
          )}
          <span className={i < revealed ? "text-slate-200" : "text-[var(--color-text-faint)]"}>{label}</span>
        </li>
      ))}
    </ul>
  );
}
