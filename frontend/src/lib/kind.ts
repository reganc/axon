// Shared node-kind presentation (glyph + label), used by the canvas, search
// results, and the node-detail page.
export const KIND_GLYPH: Record<string, string> = {
  concept: "●",
  apply: "⚙",
  question: "?",
  person: "◆",
  artifact: "▤",
  project: "▣",
  skill: "✦",
};

export function kindGlyph(kind?: string): string {
  return (kind && KIND_GLYPH[kind]) || "●";
}
