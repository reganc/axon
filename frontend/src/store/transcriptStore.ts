import { create } from "zustand";
import type { NeighborGraph, StreamEvent } from "@/lib/types";

export interface TMessage {
  id: string;
  kind: "say" | "status";
  text: string;
}

export type MediaItem =
  | { kind: "video"; url: string }
  | { kind: "link"; url: string; title?: string }
  | { kind: "image"; url: string }
  | { kind: "diagram"; mermaid: string }
  | { kind: "graph"; graph: NeighborGraph };

/** A stable signature so replayed media (from the durable log) doesn't duplicate. */
function mediaKey(m: MediaItem): string {
  if (m.kind === "diagram") return `diagram:${m.mermaid}`;
  if (m.kind === "graph") return `graph:${m.graph.anchor}`;
  return `${m.kind}:${m.url}`;
}

type MediaData = Extract<StreamEvent, { type: "media" }>["data"];

/** Map a `media` event payload to a typed MediaItem, dropping malformed ones. */
function toMediaItem(d: MediaData): MediaItem | null {
  switch (d.media_kind) {
    case "video":
      return d.url ? { kind: "video", url: d.url } : null;
    case "link":
      return d.url ? { kind: "link", url: d.url, title: d.title } : null;
    case "image":
      return d.url ? { kind: "image", url: d.url } : null;
    case "diagram":
      return d.mermaid ? { kind: "diagram", mermaid: d.mermaid } : null;
    case "graph":
      return d.graph ? { kind: "graph", graph: d.graph } : null;
    default:
      return null;
  }
}

export interface AskState {
  prompt: string;
  options?: string[];
}

export interface DiscussTurn {
  role: "learner" | "tutor";
  text: string;
}

interface TranscriptState {
  checkoutId: string | null;
  messages: TMessage[];
  ask: AskState | null;
  busy: boolean;
  // Deep-dive narration accumulated per node id (the streamed explanation of a
  // selected card). Keyed so re-opening a card shows its explanation instantly.
  deepDives: Record<string, string>;
  // The back-and-forth follow-up chat per node id. Once a discussion starts for a
  // card, the Tutor's `say` lines append here as bubbles instead of the intro.
  discussions: Record<string, DiscussTurn[]>;
  // Validated visual aids per node id (video/link/image/diagram/mini-graph).
  media: Record<string, MediaItem[]>;
  init: (checkoutId: string) => void;
  setBusy: (busy: boolean) => void;
  apply: (ev: StreamEvent) => void;
  reset: () => void;
}

const key = (id: string) => `axon.transcript.${id}`;
let seq = 0;

function persist(state: TranscriptState) {
  if (typeof window === "undefined" || !state.checkoutId) return;
  sessionStorage.setItem(
    key(state.checkoutId),
    JSON.stringify({
      messages: state.messages,
      ask: state.ask,
      deepDives: state.deepDives,
      discussions: state.discussions,
      media: state.media,
    }),
  );
}

type Restored = {
  messages: TMessage[];
  ask: AskState | null;
  deepDives?: Record<string, string>;
  discussions?: Record<string, DiscussTurn[]>;
  media?: Record<string, MediaItem[]>;
};

export const useTranscriptStore = create<TranscriptState>((set, get) => ({
  checkoutId: null,
  messages: [],
  ask: null,
  busy: false,
  deepDives: {},
  discussions: {},
  media: {},

  init: (checkoutId) => {
    let restored: Restored = { messages: [], ask: null, deepDives: {} };
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
    set({
      checkoutId,
      messages: restored.messages ?? [],
      ask: restored.ask ?? null,
      deepDives: restored.deepDives ?? {},
      discussions: restored.discussions ?? {},
      media: restored.media ?? {},
      busy: false,
    });
  },

  setBusy: (busy) => set({ busy }),

  apply: (ev) => {
    set((s) => {
      if (ev.type === "discuss") {
        // The learner's echoed turn (or a replayed one) opens the card's thread.
        const id = ev.data.node_id;
        const thread = [...(s.discussions[id] ?? []), { role: ev.data.role, text: ev.data.text }];
        return { discussions: { ...s.discussions, [id]: thread } };
      }
      if (ev.type === "media") {
        const item = toMediaItem(ev.data);
        if (!item) return s;
        const id = ev.data.node_id;
        const list = s.media[id] ?? [];
        // Replay (durable log) re-emits media; don't duplicate it.
        if (list.some((m) => mediaKey(m) === mediaKey(item))) return s;
        return { media: { ...s.media, [id]: [...list, item] } };
      }
      if (ev.type === "say") {
        const message: TMessage = { id: `m${seq++}`, kind: "say", text: ev.data.text };
        if (ev.data.node_id) {
          const id = ev.data.node_id;
          const ongoing = s.discussions[id];
          // Once a discussion is underway, the Tutor's lines append to the thread
          // as bubbles (a new tutor turn, or streamed onto the latest one).
          if (ongoing && ongoing.length > 0) {
            const thread = [...ongoing];
            const last = thread[thread.length - 1];
            if (last.role === "tutor") {
              thread[thread.length - 1] = {
                role: "tutor",
                text: `${last.text} ${ev.data.text}`,
              };
            } else {
              thread.push({ role: "tutor", text: ev.data.text });
            }
            return {
              messages: [...s.messages, message],
              discussions: { ...s.discussions, [id]: thread },
            };
          }
          // No discussion yet: accumulate the opening deep-dive narration so the
          // card reader can show (and replay) the streamed explanation.
          const prev = s.deepDives[id] ?? "";
          const deepDives = {
            ...s.deepDives,
            [id]: prev ? `${prev} ${ev.data.text}` : ev.data.text,
          };
          return { messages: [...s.messages, message], deepDives };
        }
        return { messages: [...s.messages, message] };
      }
      if (ev.type === "status") {
        const text = ev.data.detail ?? ev.data.phase ?? "";
        if (!text) return s;
        return { messages: [...s.messages, { id: `m${seq++}`, kind: "status", text }] };
      }
      if (ev.type === "ask") {
        return {
          ask: { prompt: ev.data.prompt, options: ev.data.options },
          messages: [...s.messages, { id: `m${seq++}`, kind: "say", text: ev.data.prompt }],
          busy: false,
        };
      }
      if (ev.type === "done") {
        return { ask: null, busy: false };
      }
      return s;
    });
    persist(get());
  },

  reset: () => {
    const id = get().checkoutId;
    if (typeof window !== "undefined" && id) sessionStorage.removeItem(key(id));
    set({
      messages: [],
      ask: null,
      busy: false,
      deepDives: {},
      discussions: {},
      media: {},
    });
  },
}));
