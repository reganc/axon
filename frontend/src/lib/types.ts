// Types mirroring the backend DTOs (app/ports.py) and the companion event
// contract (specs/02-phase-2-companion.md). Keep in sync with the backend.

export type Role = "learner" | "author" | "admin";

export interface SpineSummary {
  id: string;
  title: string;
  subject: string;
  description?: string | null;
  node_count: number;
}

export interface FacetValue {
  label: string;
  node_count: number;
  sample_titles: string[];
}

export interface FacetGroup {
  dimension: string;
  values: FacetValue[];
}

export interface Facets {
  node_total: number;
  groups: FacetGroup[];
}

export interface NodeDTO {
  id: string;
  canonical_key: string;
  title: string;
  kind: string;
  hook?: string | null;
  body?: string | null;
  origin: string;
  confidence: number;
  locked: boolean;
  attributes?: Record<string, unknown>;
}

// A small neighborhood of the graph around one node, for the card's mini-graph.
export interface NeighborGraph {
  anchor: string;
  nodes: { id: string; title: string; kind: string }[];
  edges: { src: string; dst: string; type: string }[];
}

export interface SpineWithNodes {
  id: string;
  title: string;
  subject: string;
  nodes: NodeDTO[];
}

export interface NodeState {
  checkout_id: string;
  node_id: string;
  mastery: number;
  next_review_at?: string | null;
  learner_notes?: string | null;
}

export interface Checkout {
  id: string;
  user_id: string;
  spine_id?: string | null;
  subject?: string | null;
}

export interface CheckoutSummary {
  id: string;
  subject?: string | null;
  spine_id?: string | null;
  spine_title?: string | null;
  created_at: string;
  last_activity?: string | null;
  message_count: number;
}

export interface EdgeDTO {
  id: string;
  src_node: string;
  dst_node: string;
  type: string;
}

// Server -> client stream events. The frontend demuxes this one stream into the
// graph canvas (node/edge) and the companion transcript (say/ask/status).
export type StreamEvent =
  // `node_id` is set on deep-dive narration so it can be pinned to the open card.
  | { type: "say"; data: { text: string; node_id?: string } }
  | { type: "ask"; data: { prompt: string; options?: string[] } }
  // One turn of a node-scoped discussion. The learner's own turn is echoed so the
  // durable log replays both sides; tutor answers stream back as `say` events.
  | {
      type: "discuss";
      data: { node_id: string; role: "learner" | "tutor"; text: string };
    }
  // A validated visual aid pinned to a card: a video/link/image, a generated
  // Mermaid diagram, or a neighbor mini-graph.
  | {
      type: "media";
      data: {
        node_id: string;
        media_kind: "video" | "link" | "image" | "diagram" | "graph";
        url?: string;
        title?: string;
        mermaid?: string;
        graph?: NeighborGraph;
      };
    }
  | { type: "node.create"; data: { temp_id: string; node: Partial<NodeDTO>; reused?: boolean } }
  | {
      type: "node.update";
      data: { temp_id: string; canonical_id: string; patch: Record<string, unknown> };
    }
  | { type: "edge.create"; data: { edge: EdgeDTO } }
  | { type: "status"; data: { phase?: string; detail?: string } }
  | { type: "done"; data: { nodes?: number } };

// How an explanation is pitched to the learner. A transient, per-session
// presentation hint — it shapes only the spoken/streamed talk, never the graph.
export type DeliveryLevel = "kid" | "high_school" | "undergrad" | "expert";

// Client -> server messages.
export type ClientMessage =
  | { type: "subject"; text: string }
  | { type: "interrupt"; text: string }
  | { type: "answer"; text: string }
  | { type: "pull_thread"; node_id: string }
  | { type: "explore_question"; node_id: string }
  | { type: "explain"; node_id: string; depth?: number }
  | { type: "discuss"; node_id: string; text: string }
  | { type: "set_level"; level: DeliveryLevel | null }
  | { type: "request_media"; node_id: string }
  | { type: "close" };
