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

interface TranscriptState {
  checkoutId: string | null;
  messages: TMessage[];
  ask: AskState | null;
  busy: boolean;
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
    JSON.stringify({ messages: state.messages, ask: state.ask }),
  );
}

export const useTranscriptStore = create<TranscriptState>((set, get) => ({
  checkoutId: null,
  messages: [],
  ask: null,
  busy: false,

  init: (checkoutId) => {
    let restored: { messages: TMessage[]; ask: AskState | null } = {
      messages: [],
      ask: null,
    };
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
    set({ checkoutId, ...restored, busy: false });
  },

  setBusy: (busy) => set({ busy }),

  apply: (ev) => {
    set((s) => {
      if (ev.type === "say") {
        return { messages: [...s.messages, { id: `m${seq++}`, kind: "say", text: ev.data.text }] };
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
    set({ messages: [], ask: null, busy: false });
  },
}));
