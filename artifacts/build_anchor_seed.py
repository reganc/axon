#!/usr/bin/env python3
"""
build_anchor_seed.py — curated cold-start anchors (Phase 5 §6).

Emits anchor_seed.json in the same shape the existing loader ingests
(`IngestionPort.ingest_seed`): a small set of `question` anchors (great questions
with strong hooks and NO answer body — opening one seeds generation) and `person`
anchors (key thinkers with grounded attributes). All origin=authored, locked=true.

These are *evocative entry points that seed generation*, not content. The target
is hundreds, not thousands; this ships a curated starter set that the same
idempotent loader extends. ids are uuid5 so re-running changes nothing.

Run:  python build_anchor_seed.py   ->  anchor_seed.json
"""
import json
import uuid

NS = uuid.uuid5(uuid.NAMESPACE_URL, "lms://anchor-seed/v1")


def nid(key: str) -> str:
    return str(uuid.uuid5(NS, key))


SOURCE = {
    "id": nid("source:anchors"),
    "kind": "anchor_set",
    "title": "AXON cold-start curiosity anchors",
    "uri": "anchors/",
    "ingested_at": None,
}

N: list[dict] = []


def question(key: str, title: str, hook: str, difficulty: str) -> None:
    N.append(
        {
            "id": nid(key), "canonical_key": key, "title": title, "kind": "question",
            "hook": hook, "body": None, "apply_prompt": None,
            "recall_prompts": [], "mastery_criteria": [], "depth_level": "intro",
            "embedding": None, "origin": "authored", "locked": True,
            "source_ref": "anchors#question", "confidence": 1.0, "version": 1,
            "quality_signals": {},
            "attributes": {"status": "open", "difficulty": difficulty},
        }
    )


def person(key: str, title: str, bio: str, attrs: dict) -> None:
    N.append(
        {
            "id": nid(key), "canonical_key": key, "title": title, "kind": "person",
            "hook": f"The mind behind {title.split()[-1]}'s ideas — pull a thread to follow them.",
            "body": bio, "apply_prompt": None,
            "recall_prompts": [], "mastery_criteria": [], "depth_level": "intro",
            "embedding": None, "origin": "authored", "locked": True,
            "source_ref": "anchors#person", "confidence": 1.0, "version": 1,
            "quality_signals": {}, "attributes": attrs,
        }
    )


# --- great questions (no answer bodies — they seed generation) ---------------
question("anchor-what-is-intelligence", "What is intelligence?",
         "Everyone uses the word; nobody agrees what it measures. Is it one thing or many?", "hard")
question("anchor-how-does-a-brain-learn", "How does a brain learn?",
         "Three pounds of tissue rewires itself from experience. What's the rule it follows?", "hard")
question("anchor-what-is-consciousness", "What is consciousness?",
         "Why is there something it is like to be you — and could a machine ever have it?", "hard")
question("anchor-can-a-machine-understand", "Can a machine truly understand?",
         "A model can finish your sentence flawlessly. Does it grasp the meaning, or just the statistics?", "core")
question("anchor-why-is-math-so-effective", "Why is mathematics so effective?",
         "Marks on paper predict the orbit of planets and the mass of particles. Why should that work at all?", "hard")
question("anchor-what-makes-a-system-alive", "What makes a system alive?",
         "Where exactly is the line between chemistry and life — and is it a line at all?", "core")

# --- key thinkers (grounded attributes) --------------------------------------
person("anchor-person-alan-turing", "Alan Turing",
       "Founder of theoretical computer science; defined computation with the Turing machine and "
       "posed the question of machine intelligence with the imitation game.",
       {"born": 1912, "died": 1954, "country": "United Kingdom",
        "notable_for": ["Turing machine", "Turing test", "computability"]})
person("anchor-person-claude-shannon", "Claude Shannon",
       "Founder of information theory; showed that information could be measured in bits and "
       "communicated reliably over noisy channels.",
       {"born": 1916, "died": 2001, "country": "United States",
        "notable_for": ["information theory", "the bit", "channel capacity"]})
person("anchor-person-geoffrey-hinton", "Geoffrey Hinton",
       "A central figure in deep learning; advanced backpropagation and representation learning and "
       "shared the 2018 Turing Award with LeCun and Bengio.",
       {"born": 1947, "country": "United Kingdom / Canada",
        "notable_for": ["backpropagation", "deep learning", "2018 Turing Award"]})

# --- a few 'about' edges: a thinker is associated with a question ------------
E: list[dict] = []


def edge(src: str, dst: str, typ: str) -> None:
    E.append(
        {"id": nid(f"edge:{src}->{dst}:{typ}"), "src_node": nid(src), "dst_node": nid(dst),
         "type": typ, "weight": 1.0, "origin": "authored"}
    )


edge("anchor-person-alan-turing", "anchor-can-a-machine-understand", "about")
edge("anchor-person-geoffrey-hinton", "anchor-how-does-a-brain-learn", "about")
edge("anchor-person-claude-shannon", "anchor-why-is-math-so-effective", "about")

out = {"sources": [SOURCE], "nodes": N, "edges": E, "spines": []}
with open("anchor_seed.json", "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)

ids = {n["id"] for n in N}
bad = [e for e in E if e["src_node"] not in ids or e["dst_node"] not in ids]
assert not bad, f"dangling edges: {bad}"
print(f"anchors: {len(N)} nodes ({sum(n['kind']=='question' for n in N)} questions, "
      f"{sum(n['kind']=='person' for n in N)} people), {len(E)} edges — validation OK")
