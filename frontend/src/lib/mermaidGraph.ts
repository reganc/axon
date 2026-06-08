import type { NeighborGraph } from "./types";

// Mermaid node ids must be simple tokens, and labels can't contain quotes or
// the bracket/pipe characters Mermaid uses for syntax. Map each canonical id to a
// safe alias and sanitize titles so a node title never breaks the diagram.
function sanitizeLabel(text: string): string {
  return text.replace(/["[\]{}|<>]/g, " ").replace(/\s+/g, " ").trim().slice(0, 36);
}

/** Render a node's neighborhood as a Mermaid flowchart, with the anchor node
 *  highlighted. Returns null when there's nothing worth drawing. */
export function neighborGraphToMermaid(g: NeighborGraph): string | null {
  if (!g.nodes.length || !g.edges.length) return null;
  const alias = new Map<string, string>();
  g.nodes.forEach((n, i) => alias.set(n.id, `n${i}`));

  const lines: string[] = ["graph LR"];
  for (const n of g.nodes) {
    const id = alias.get(n.id);
    if (!id) continue;
    lines.push(`${id}["${sanitizeLabel(n.title) || n.kind}"]`);
  }
  for (const e of g.edges) {
    const src = alias.get(e.src);
    const dst = alias.get(e.dst);
    if (!src || !dst) continue;
    const label = sanitizeLabel(e.type.replace(/_/g, " "));
    lines.push(label ? `${src} -->|${label}| ${dst}` : `${src} --> ${dst}`);
  }
  const anchor = alias.get(g.anchor);
  if (anchor) {
    lines.push("classDef anchor stroke-width:2px;");
    lines.push(`class ${anchor} anchor;`);
  }
  return lines.join("\n");
}
