import { beforeEach, describe, expect, it } from "vitest";
import type { StreamEvent } from "@/lib/types";
import { useTranscriptStore } from "./transcriptStore";

const say = (text: string, nodeId?: string): StreamEvent => ({
  type: "say",
  data: nodeId ? { text, node_id: nodeId } : { text },
});

describe("transcriptStore deep-dive routing", () => {
  beforeEach(() => {
    useTranscriptStore.getState().init("test-checkout");
    useTranscriptStore.getState().reset();
    useTranscriptStore.setState({ checkoutId: "test-checkout" });
  });

  it("accumulates node-tagged say events under that node id", () => {
    const { apply } = useTranscriptStore.getState();
    apply(say("First sentence.", "node-1"));
    apply(say("Second sentence.", "node-1"));

    const { deepDives, messages } = useTranscriptStore.getState();
    expect(deepDives["node-1"]).toBe("First sentence. Second sentence.");
    // narration still flows into the transcript (so it's spoken / shown as subtitle)
    expect(messages.filter((m) => m.kind === "say")).toHaveLength(2);
  });

  it("keeps general narration out of the deep-dive map", () => {
    const { apply } = useTranscriptStore.getState();
    apply(say("Here's a new idea: X."));

    const { deepDives, messages } = useTranscriptStore.getState();
    expect(Object.keys(deepDives)).toHaveLength(0);
    expect(messages).toHaveLength(1);
  });

  it("separates deep dives by node id", () => {
    const { apply } = useTranscriptStore.getState();
    apply(say("About A.", "a"));
    apply(say("About B.", "b"));

    const { deepDives } = useTranscriptStore.getState();
    expect(deepDives.a).toBe("About A.");
    expect(deepDives.b).toBe("About B.");
  });
});
