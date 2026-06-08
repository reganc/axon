import { create } from "zustand";
import type { StreamEvent } from "@/lib/types";

export interface TMessage {
  id: string;
  kind: "say" | "status";
  text: string;
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
    }),
  );
}

type Restored = {
  messages: TMessage[];
  ask: AskState | null;
  deepDives?: Record<string, string>;
  discussions?: Record<string, DiscussTurn[]>;
};

export const useTranscriptStore = create<TranscriptState>((set, get) => ({
  checkoutId: null,
  messages: [],
  ask: null,
  busy: false,
  deepDives: {},
  discussions: {},

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
    set({ messages: [], ask: null, busy: false, deepDives: {}, discussions: {} });
  },
}));
