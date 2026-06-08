import { beforeEach, describe, expect, it } from "vitest";
import type { StreamEvent } from "@/lib/types";
import { useGraphStore } from "./graphStore";

const reset = () => useGraphStore.getState().reset();

const createNode = (tempId: string, title: string): StreamEvent => ({
  type: "node.create",
  data: { temp_id: tempId, node: { title, kind: "concept" } },
});

const updateNode = (tempId: string, canonicalId: string): StreamEvent => ({
  type: "node.update",
  data: { temp_id: tempId, canonical_id: canonicalId, patch: { origin: "generated" } },
});

describe("graphStore.apply", () => {
  beforeEach(() => {
    useGraphStore.getState().init("test-checkout");
    reset();
    useGraphStore.setState({ checkoutId: "test-checkout" });
  });

  it("keeps order unique when two optimistic nodes merge into one canonical node", () => {
    const { apply } = useGraphStore.getState();
    apply(createNode("t1", "Backprop"));
    apply(createNode("t2", "Backpropagation"));
    // Both temps canonicalize into the SAME node (library collapsing duplicates).
    apply(updateNode("t1", "canon-A"));
    apply(updateNode("t2", "canon-A"));

    const { order, nodes } = useGraphStore.getState();
    expect(order).toEqual(["canon-A"]);
    expect(new Set(order).size).toBe(order.length); // no duplicate keys
    expect(nodes["canon-A"].optimistic).toBe(false);
    expect(nodes.t1).toBeUndefined();
    expect(nodes.t2).toBeUndefined();
  });

  it("preserves spine status when a temp canonicalizes into a seeded spine node", () => {
    const { apply, seedSpine } = useGraphStore.getState();
    seedSpine([
      {
        id: "canon-spine",
        canonical_key: "k",
        title: "Gradient Descent",
        kind: "concept",
        origin: "authored",
        confidence: 1,
        locked: true,
      },
    ]);
    apply(createNode("t1", "Gradient descent (dup)"));
    apply(updateNode("t1", "canon-spine"));

    const { order, nodes } = useGraphStore.getState();
    expect(order.filter((id) => id === "canon-spine")).toHaveLength(1);
    expect(nodes["canon-spine"].onSpine).toBe(true);
  });

  it("repoints edges from temp id to canonical id", () => {
    const { apply } = useGraphStore.getState();
    apply(createNode("t1", "A"));
    apply(createNode("t2", "B"));
    apply({
      type: "edge.create",
      data: { edge: { id: "e1", src_node: "t1", dst_node: "t2", type: "relates_to" } },
    });
    apply(updateNode("t1", "canon-A"));

    const { edges } = useGraphStore.getState();
    expect(edges.e1.source).toBe("canon-A");
    expect(edges.e1.target).toBe("t2");
  });
});
