"use client";
import type { DeliveryLevel } from "@/lib/types";

// `null` = unconditioned: the companion explains in its natural register, with
// no audience clause added to the prompt (the baseline behaviour).
const UNCONDITIONED = "default";

const OPTIONS: { value: DeliveryLevel | typeof UNCONDITIONED; label: string }[] = [
  { value: UNCONDITIONED, label: "Default" },
  { value: "kid", label: "Kid" },
  { value: "high_school", label: "High school" },
  { value: "undergrad", label: "Undergrad" },
  { value: "expert", label: "Expert" },
];

interface Props {
  value: DeliveryLevel | null;
  onChange: (level: DeliveryLevel | null) => void;
}

/** Picks how the companion pitches its spoken/streamed explanations. A
 *  presentation hint only — the same nodes are generated and stored regardless,
 *  so changing it never alters the shared knowledge graph. "Default" leaves the
 *  talk unconditioned. */
export function LevelSelector({ value, onChange }: Props) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-muted">
      <span className="hidden sm:inline">Level</span>
      <select
        value={value ?? UNCONDITIONED}
        onChange={(e) => {
          const v = e.target.value;
          onChange(v === UNCONDITIONED ? null : (v as DeliveryLevel));
        }}
        aria-label="Explanation level"
        title="How explanations are pitched — shapes the talk only, not the graph"
        className="rounded-full border border-border bg-surface px-2.5 py-1 text-fg outline-none focus:border-accent"
      >
        {OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
