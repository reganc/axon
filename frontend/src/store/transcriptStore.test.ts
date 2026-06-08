import { beforeEach, describe, expect, it } from "vitest";
import type { StreamEvent } from "@/lib/types";
import { useTranscriptStore } from "./transcriptStore";

const say = (text: string, nodeId?: string): StreamEvent => ({
  type: "say",
  data: nodeId ? { text, node_id: nodeId } : { text },
});

const discuss = (
  nodeId: string,
  role: "learner" | "tutor",
  text: string,
): StreamEvent => ({ type: "discuss", data: { node_id: nodeId, role, text } });

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

describe("transcriptStore discussion threading", () => {
  beforeEach(() => {
    useTranscriptStore.getState().init("test-checkout");
    useTranscriptStore.getState().reset();
    useTranscriptStore.setState({ checkoutId: "test-checkout" });
  });

  it("opens a thread on a learner turn and streams the tutor reply into one bubble", () => {
    const { apply } = useTranscriptStore.getState();
    // opening deep-dive narration lands in the intro, not the thread
    apply(say("The intro explanation.", "n1"));
    // learner asks a follow-up; tutor answer streams as two say events
    apply(discuss("n1", "learner", "But why does that hold?"));
    apply(say("Because of this.", "n1"));
    apply(say("And also that.", "n1"));

    const { deepDives, discussions } = useTranscriptStore.getState();
    expect(deepDives.n1).toBe("The intro explanation.");
    expect(discussions.n1).toEqual([
      { role: "learner", text: "But why does that hold?" },
      { role: "tutor", text: "Because of this. And also that." },
    ]);
  });

  it("keeps multiple exchanges as separate bubbles", () => {
    const { apply } = useTranscriptStore.getState();
    apply(say("Intro.", "n1"));
    apply(discuss("n1", "learner", "Q1"));
    apply(say("A1.", "n1"));
    apply(discuss("n1", "learner", "Q2"));
    apply(say("A2.", "n1"));

    const { discussions } = useTranscriptStore.getState();
    expect(discussions.n1.map((t) => t.role)).toEqual([
      "learner",
      "tutor",
      "learner",
      "tutor",
    ]);
    expect(discussions.n1[3]).toEqual({ role: "tutor", text: "A2." });
  });

  it("scopes discussions to their node id", () => {
    const { apply } = useTranscriptStore.getState();
    apply(discuss("a", "learner", "about a"));
    apply(say("answer a", "a"));
    apply(discuss("b", "learner", "about b"));

    const { discussions } = useTranscriptStore.getState();
    expect(discussions.a).toHaveLength(2);
    expect(discussions.b).toEqual([{ role: "learner", text: "about b" }]);
  });
});
