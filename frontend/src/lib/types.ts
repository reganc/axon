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

export interface EdgeDTO {
  id: string;
  src_node: string;
  dst_node: string;
  type: string;
}

// Server -> client stream events. The frontend demuxes this one stream into the
// graph canvas (node/edge) and the companion transcript (say/ask/status).
export type StreamEvent =
  | { type: "say"; data: { text: string } }
  | { type: "ask"; data: { prompt: string; options?: string[] } }
  | { type: "node.create"; data: { temp_id: string; node: Partial<NodeDTO>; reused?: boolean } }
  | {
      type: "node.update";
      data: { temp_id: string; canonical_id: string; patch: Record<string, unknown> };
    }
  | { type: "edge.create"; data: { edge: EdgeDTO } }
  | { type: "status"; data: { phase?: string; detail?: string } }
  | { type: "done"; data: { nodes?: number } };

// Client -> server messages.
export type ClientMessage =
  | { type: "subject"; text: string }
  | { type: "interrupt"; text: string }
  | { type: "answer"; text: string }
  | { type: "pull_thread"; node_id: string }
  | { type: "explore_question"; node_id: string }
  | { type: "close" };
