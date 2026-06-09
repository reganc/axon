"use client";
import type { DeliveryLevel } from "@/lib/types";

const LEVELS: { value: DeliveryLevel; label: string }[] = [
  { value: "kid", label: "Kid" },
  { value: "high_school", label: "High school" },
  { value: "undergrad", label: "Undergrad" },
  { value: "expert", label: "Expert" },
];

interface Props {
  value: DeliveryLevel;
  onChange: (level: DeliveryLevel) => void;
}

/** Picks how the companion pitches its spoken/streamed explanations. A
 *  presentation hint only — the same nodes are generated and stored regardless,
 *  so changing it never alters the shared knowledge graph. */
export function LevelSelector({ value, onChange }: Props) {
  return (
    <label className="flex items-center gap-1.5 text-xs text-muted">
      <span className="hidden sm:inline">Level</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as DeliveryLevel)}
        aria-label="Explanation level"
        title="How explanations are pitched — shapes the talk only, not the graph"
        className="rounded-full border border-border bg-surface px-2.5 py-1 text-fg outline-none focus:border-accent"
      >
        {LEVELS.map((l) => (
          <option key={l.value} value={l.value}>
            {l.label}
          </option>
        ))}
      </select>
    </label>
  );
}
