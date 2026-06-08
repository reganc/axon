import { describe, expect, it } from "vitest";
import { neighborGraphToMermaid } from "./mermaidGraph";
import type { NeighborGraph } from "./types";

const g = (over: Partial<NeighborGraph> = {}): NeighborGraph => ({
  anchor: "a",
  nodes: [
    { id: "a", title: "Convolution", kind: "concept" },
    { id: "b", title: "Pooling", kind: "concept" },
  ],
  edges: [{ src: "a", dst: "b", type: "next_in_spine" }],
  ...over,
});

describe("neighborGraphToMermaid", () => {
  it("builds a flowchart with aliased ids, labels, and an anchor class", () => {
    const out = neighborGraphToMermaid(g());
    expect(out).not.toBeNull();
    const code = out as string;
    expect(code.startsWith("graph LR")).toBe(true);
    expect(code).toContain('n0["Convolution"]');
    expect(code).toContain('n1["Pooling"]');
    expect(code).toContain("n0 -->|next in spine| n1");
    expect(code).toContain("class n0 anchor;");
  });

  it("returns null when there is nothing to draw", () => {
    expect(neighborGraphToMermaid(g({ edges: [] }))).toBeNull();
    expect(neighborGraphToMermaid(g({ nodes: [] }))).toBeNull();
  });

  it("sanitizes titles so a stray quote/bracket can't break the diagram", () => {
    const code = neighborGraphToMermaid(
      g({
        nodes: [
          { id: "a", title: 'Weird "title" [x]', kind: "concept" },
          { id: "b", title: "Plain", kind: "concept" },
        ],
      }),
    ) as string;
    expect(code).not.toContain('"title"');
    expect(code).not.toContain("[x]");
  });
});
