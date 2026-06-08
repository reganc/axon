import { create } from "zustand";
import type { NodeDTO, StreamEvent } from "@/lib/types";

export interface GNode {
  id: string;
  title: string;
  kind?: string;
  hook?: string | null;
  body?: string | null;
  origin?: string;
  confidence?: number;
  onSpine: boolean;
  optimistic: boolean;
  flagged?: boolean;
}

export interface GEdge {
  id: string;
  source: string;
  target: string;
  type: string;
}

interface GraphState {
  checkoutId: string | null;
  nodes: Record<string, GNode>;
  edges: Record<string, GEdge>;
  order: string[];
  selectedId: string | null;
  init: (checkoutId: string) => void;
  seedSpine: (nodes: NodeDTO[]) => void;
  apply: (ev: StreamEvent) => void;
  select: (id: string | null) => void;
  reset: () => void;
}

const key = (id: string) => `axon.graph.${id}`;

function persist(state: GraphState) {
  if (typeof window === "undefined" || !state.checkoutId) return;
  const { nodes, edges, order } = state;
  sessionStorage.setItem(key(state.checkoutId), JSON.stringify({ nodes, edges, order }));
}

export const useGraphStore = create<GraphState>((set, get) => ({
  checkoutId: null,
  nodes: {},
  edges: {},
  order: [],
  selectedId: null,

  init: (checkoutId) => {
    let restored = { nodes: {}, edges: {}, order: [] as string[] };
    if (typeof window !== "undefined") {
      const raw = sessionStorage.getItem(key(checkoutId));
      if (raw) {
        try {
          restored = JSON.parse(raw);
        } catch {
          /* ignore corrupt snapshot */
        }
      }
    }
    set({ checkoutId, ...restored, selectedId: null });
  },

  seedSpine: (nodes) => {
    set((s) => {
      const next = { ...s.nodes };
      const order = [...s.order];
      for (const n of nodes) {
        if (!next[n.id]) order.push(n.id);
        next[n.id] = {
          id: n.id,
          title: n.title,
          kind: n.kind,
          hook: n.hook,
          body: n.body,
          origin: n.origin,
          confidence: n.confidence,
          onSpine: true,
          optimistic: false,
        };
      }
      return { nodes: next, order };
    });
    persist(get());
  },

  apply: (ev) => {
    set((s) => {
      const nodes = { ...s.nodes };
      const edges = { ...s.edges };
      let order = [...s.order];

      if (ev.type === "node.create") {
        const id = ev.data.temp_id;
        if (!nodes[id]) order.push(id);
        nodes[id] = {
          id,
          title: ev.data.node.title ?? "…",
          kind: ev.data.node.kind,
          hook: ev.data.node.hook,
          body: ev.data.node.body,
          origin: ev.data.node.origin,
          confidence: ev.data.node.confidence,
          onSpine: false,
          optimistic: !ev.data.reused,
        };
      } else if (ev.type === "node.update") {
        const temp = nodes[ev.data.temp_id];
        const canonicalId = ev.data.canonical_id;
        if (temp) {
          const patch = ev.data.patch as Record<string, unknown>;
          const existing = nodes[canonicalId];
          const merged: GNode = {
            ...temp,
            id: canonicalId,
            optimistic: false,
            // A temp can canonicalize *into* a node that's already on the spine;
            // keep its spine status so layout/position don't flip.
            onSpine: temp.onSpine || (existing?.onSpine ?? false),
            origin: (patch.origin as string) ?? temp.origin,
            confidence: (patch.confidence as number) ?? temp.confidence,
            flagged: Boolean(patch.flagged_low_confidence),
          };
          delete nodes[ev.data.temp_id];
          nodes[canonicalId] = merged;
          // Remap temp_id -> canonicalId in the order list, then de-duplicate.
          // Two optimistic nodes can merge into one canonical node (the library
          // collapsing duplicates), which would otherwise leave canonicalId in
          // `order` twice -> duplicate React keys and duplicated/omitted cards.
          const seen = new Set<string>();
          order = order
            .map((o) => (o === ev.data.temp_id ? canonicalId : o))
            .filter((o) => {
              if (seen.has(o)) return false;
              seen.add(o);
              return true;
            });
          // repoint any edges that referenced the temp id
          for (const e of Object.values(edges)) {
            if (e.source === ev.data.temp_id) e.source = canonicalId;
            if (e.target === ev.data.temp_id) e.target = canonicalId;
          }
        }
      } else if (ev.type === "edge.create") {
        const e = ev.data.edge;
        edges[e.id] = { id: e.id, source: e.src_node, target: e.dst_node, type: e.type };
      }
      return { nodes, edges, order };
    });
    persist(get());
  },

  select: (id) => set({ selectedId: id }),

  reset: () => {
    const id = get().checkoutId;
    if (typeof window !== "undefined" && id) sessionStorage.removeItem(key(id));
    set({ nodes: {}, edges: {}, order: [], selectedId: null });
  },
}));
