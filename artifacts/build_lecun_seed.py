#!/usr/bin/env python3
"""
build_lecun_seed.py — atomize the 3 'Understanding Yann LeCun' courses into the
canonical knowledge graph (sub-concept granularity) and emit a validated seed.

Run:  python build_lecun_seed.py
Out:  lecun_seed_graph.json   (sources, nodes, edges, spines)

Notes
- ids are uuid5(NAMESPACE, canonical_key) so re-running is idempotent and the
  same concept always resolves to the same uuid (the dedup property, by construction).
- bodies are faithful condensations of the author's lesson content; HOOKS are the
  one generated layer — the seed courses open with definitions, which is exactly
  what the new model inverts.
- embeddings are left null; the loader computes them (Ollama nomic-embed-text)
  at insert time, which is also where runtime canonicalization happens.
"""
import json, uuid

NS = uuid.uuid5(uuid.NAMESPACE_URL, "lms://lecun-seed/v1")
def nid(key): return str(uuid.uuid5(NS, key))

SOURCE = {
    "id": str(uuid.uuid5(NS, "source:lecun-course")),
    "kind": "markdown_course",
    "title": "Understanding Yann LeCun — 3-course learning path",
    "uri": "lecun-course/",
    "ingested_at": None,
}

# --- nodes -------------------------------------------------------------------
# (key, title, kind, hook, body, recall[], criteria[], depth, source_ref, apply_prompt)
N = []
def node(key, title, hook, body, recall, criteria, depth, ref, kind="concept", apply=None, attributes=None):
    N.append({
        "id": nid(key), "canonical_key": key, "title": title, "kind": kind,
        "hook": hook, "body": body, "apply_prompt": apply,
        "recall_prompts": recall, "mastery_criteria": criteria,
        "depth_level": depth, "embedding": None,
        "origin": "authored", "locked": True, "source_ref": ref,
        "confidence": 1.0, "version": 1, "quality_signals": {},
        "attributes": attributes or {},
    })

# ===== Course 1 — The Conviction ============================================
node("connectionism-vs-symbolic-ai", "Connectionism vs. symbolic AI",
     "When LeCun started, 'AI' meant writing every rule by hand. He bet on machines that figure out the rules themselves — and was deeply unfashionable for it.",
     "Symbolic AI encodes knowledge as explicit hand-coded rules, logic, and expert systems. Connectionism takes the opposite stance: build a network of simple units and let it *learn* its internal parameters from data instead of programming knowledge in. LeCun's 1987 PhD was on connectionist learning models — a deliberate minority choice.",
     ["What's the core difference between symbolic AI and connectionism?"],
     ["Can contrast rule-encoding with learning-from-data"], "intro", "lecun/course-1#lesson-1.1")
node("lecuns-connectionist-bet", "LeCun's connectionist bet",
     "Choosing neural nets in the 1980s was a career risk bordering on reckless. Why would a young engineer wager decades on the unpopular side?",
     "LeCun (b. France, 1960; PhD 1987) bet that learning from data — not encoding rules by hand — was the path to machine intelligence, a minority position when symbolic methods held the funding and momentum. This long-horizon, against-the-grain temperament recurs throughout his career.",
     ["Why was choosing neural networks a professional risk in the 1980s?"],
     ["Can explain the early bet and the risk it carried"], "core", "lecun/course-1#lesson-1.1")
node("ai-winter", "The AI winters",
     "Twice, the whole field decided AI was a dead end and the money vanished. LeCun kept working through it anyway.",
     "An *AI winter* is a period when funding, interest, and optimism collapse after hype outruns results. LeCun spent much of the 1990s–2000s on neural networks through exactly such a stretch, when the field had largely moved on to other methods.",
     ["What is an AI winter, and what causes it?"],
     ["Can define an AI winter and its cause"], "intro", "lecun/course-1#lesson-1.2")
node("why-neural-nets-stalled", "Why neural nets stalled for 20 years",
     "The neural-net idea wasn't wrong for two decades — it was starving. Three things it was missing.",
     "Neural nets underperformed for years not because the idea was flawed but because conditions were missing: not enough labeled data, not enough compute (until GPUs were repurposed in the late 2000s), and optimization difficulties like vanishing gradients in deep stacks.",
     ["Name two practical constraints that limited neural networks before ~2010."],
     ["Can list data, compute, and optimization as the limiting factors"], "core", "lecun/course-1#lesson-1.2")
node("early-vs-wrong", "Being early vs. being wrong",
     "Being early and being wrong look identical for years. How do you tell them apart while you're living it?",
     "A transferable research skill: separating a flawed theory from an under-resourced one. LeCun's persistence wasn't stubbornness against refutation — it was a judgment that the *idea* was sound and the *conditions* simply hadn't arrived.",
     ["Why is 'being early' so hard to distinguish from 'being wrong'?"],
     ["Can articulate the early-vs-wrong distinction as a judgment skill"], "core", "lecun/course-1#lesson-1.2")
node("bell-labs-and-the-deployed-cnn", "Bell Labs and the deployed CNN",
     "Long before deep learning was cool, a LeCun system was already reading the dollar amounts on your bank checks.",
     "At AT&T Bell Labs (1988–1996) LeCun applied gradient-based learning to real recognition problems and developed the convolutional neural network into a deployable system that read handwritten digits — used commercially to read the amounts on bank checks.",
     ["What real-world product used LeCun's Bell Labs digit-recognition work?"],
     ["Can place the Bell Labs era and the check-reading deployment"], "core", "lecun/course-1#lesson-1.3")
node("the-deep-learning-trio", "The deep learning trio",
     "Three people kept neural nets alive through the lean years — and split computing's highest prize for it.",
     "LeCun did postdoctoral work with Geoffrey Hinton (his advisor and four-decade collaborator). LeCun, Hinton, and Yoshua Bengio jointly received the 2018 ACM Turing Award for deep learning. Seeing them as a connected group, not isolated geniuses, explains how the research program survived.",
     ["Who are the three recipients of the 2018 Turing Award for deep learning?"],
     ["Can identify the trio and the shared 2018 Turing Award"], "intro", "lecun/course-1#lesson-1.3")
node("the-2012-inflection", "The 2012 inflection",
     "Almost overnight, neural nets went from backwater to the main event. What flipped?",
     "Around 2012 the conditions LeCun had waited on arrived together — large labeled image datasets, fast GPUs, and refined training techniques — and deep nets abruptly started winning competitions, especially in vision. The field's center of gravity shifted.",
     ["What three things came together around 2012 to make deep learning effective?"],
     ["Can name data + GPUs + better training as the 2012 trigger"], "core", "lecun/course-1#lesson-1.4")
node("building-fair-institution", "Building an institution (FAIR)",
     "Inventing an architecture is one kind of influence. Building the lab that shapes a whole field is another.",
     "In 2013 LeCun joined Meta (then Facebook) and built its AI research organization from the ground up as Chief AI Scientist — a role held ~12 years (2013–2025) — while remaining an NYU professor and founding NYU's Center for Data Science. His influence runs through both *ideas* and *institutions*.",
     ["What role did LeCun play at Meta, and for roughly how long?"],
     ["Can describe institution-building as a distinct form of influence"], "core", "lecun/course-1#lesson-1.4")
node("lecuns-honors-and-legacy", "Honors and legacy",
     "Turing Award, Legion of Honour, National Academy of Sciences — the settled, celebrated half of the story.",
     "Beyond the 2018 Turing Award, LeCun's honors include the Queen Elizabeth Prize for Engineering, the VinFuture Prize, France's Legion of Honour, and U.S. National Academy of Sciences membership — recognizing work foundational to computer vision, document recognition, and the broader deep-learning toolkit.",
     ["Name two major awards LeCun has received."],
     ["Can list major honors recognizing his foundational work"], "intro", "lecun/course-1#lesson-1.5")
node("lecun-as-public-voice", "LeCun as public intellectual",
     "Most Turing laureates fade into quiet eminence. LeCun went the other way — picking very public fights.",
     "LeCun is one of the field's most visible and combative public voices, using talks, interviews, and social media to argue positions at odds with much of the industry — most notably that today's large language models are not the path to human-level intelligence. His legacy splits into a celebrated past and a contested present.",
     ["How is LeCun's public role different from that of a typical research scientist?"],
     ["Can characterize him as a deliberately provocative public intellectual"], "core", "lecun/course-1#lesson-1.5")
node("apply-conviction-driven-research", "Argue: is conviction repeatable?",
     "Is conviction a repeatable strategy — or just survivorship bias dressed up as wisdom? Make the argument.",
     "Course 1 project. A written argument about conviction-driven research.",
     [], ["Produces a reasoned argument using LeCun plus a counterexample"], "apply",
     "lecun/course-1#project", kind="apply",
     apply=("In 600–900 words, argue whether conviction-driven research — sticking with an unpopular idea "
            "for decades — is a repeatable strategy others should emulate, or whether it mostly looks wise "
            "in hindsight because we only remember those who turned out right (survivorship bias). Use "
            "LeCun's career as the primary example and address at least one counterexample of conviction "
            "that did NOT pay off. Assessed on reasoning and use of evidence, not which side you take."))

# ===== Course 2 — The Foundations ===========================================
node("loss-and-gradient-descent", "Loss and gradient descent",
     "Training a network is really just rolling downhill in a landscape with millions of dimensions. Here's the hill.",
     "Training is optimization. A **loss function** measures how wrong the outputs are; **gradient descent** computes the gradient (the direction of steepest increase in the loss w.r.t. each parameter) and steps the opposite way to shrink it.",
     ["What does a loss function measure, and what do we do with it?"],
     ["Can describe training as loss minimization via gradient descent"], "core", "lecun/course-2#lesson-2.1")
node("backpropagation", "Backpropagation",
     "A network can have millions of knobs. Computing how to turn each one seems hopeless — until one trick does it all in a single backward sweep.",
     "**Backpropagation** applies the chain rule systematically, working backward from the loss through each layer to compute every parameter's gradient in roughly the cost of one forward pass. This efficiency is what makes deep learning computationally possible at all.",
     ["Why is backpropagation necessary rather than computing each gradient separately?"],
     ["Can explain backprop as efficient chain-rule credit assignment"], "core", "lecun/course-2#lesson-2.1")
node("end-to-end-learning", "End-to-end learning",
     "Before LeCun, you hand-engineered features first, then learned. He showed you could feed in raw pixels and learn the whole thing at once.",
     "LeCun's foundational contribution was showing — early and convincingly — that gradient-based learning works on real recognition tasks *end to end*: a single system maps raw pixels to a decision without hand-engineered features first. That principle is now everywhere.",
     ["What does 'end-to-end learning' mean, and why did it matter?"],
     ["Can contrast end-to-end learning with hand-engineered features"], "core", "lecun/course-2#lesson-2.1")
node("the-convolutional-network", "The convolutional network",
     "Shift a cat ten pixels right and a plain network sees a totally different image. CNNs fix this with three ideas borrowed from how vision actually works.",
     "A fully connected network treats every pixel as independent — wasteful and fragile for images. The **convolutional neural network**, LeCun's signature architecture, builds in local receptive fields, weight sharing, and pooling, stacking them into a hierarchy of features from edges up to objects. It bakes in assumptions matching image structure, so it generalizes from limited data.",
     ["Why are CNNs well-suited to images?"],
     ["Can explain why CNN structure matches image structure"], "core", "lecun/course-2#lesson-2.2")
node("cnn-local-receptive-fields", "Local receptive fields",
     "Why should a unit detecting an edge bother looking at the whole image, when edges are local?",
     "Each unit looks at only a small patch of the image, because meaningful visual features (edges, corners) are local. This local receptive field is the first of the three CNN ideas.",
     ["What is a local receptive field?"],
     ["Can define local receptive fields"], "intro", "lecun/course-2#lesson-2.2")
node("cnn-weight-sharing", "Weight sharing & translation invariance",
     "A network can spot a cat in the top-left corner and go blind when the same cat slides to the bottom-right. One trick fixes it for good.",
     "The same small set of weights — a **filter** — slides across the whole image, so a feature detector (e.g. for a vertical edge) is reused everywhere. Weight sharing drastically cuts the parameter count and yields **translation invariance**: the feature is detected regardless of where it appears.",
     ["What problem does weight sharing solve compared to a fully connected network?"],
     ["Can explain weight sharing and why it gives translation invariance"], "core", "lecun/course-2#lesson-2.2")
node("cnn-pooling", "Pooling",
     "How do you make a network shrug off a few pixels of jitter — and build big-picture structure out of fine detail?",
     "**Pooling** (subsampling) periodically downsamples by summarizing a region (e.g. taking the maximum activation), adding tolerance to small shifts and distortions and building a hierarchy from fine detail to coarse structure.",
     ["What does pooling add to a CNN?"],
     ["Can explain pooling and its role in the feature hierarchy"], "intro", "lecun/course-2#lesson-2.2")
node("lenet-and-document-recognition", "LeNet and document recognition",
     "The architecture lineage in your phone's camera traces back to a 1990s network that read checks for a living.",
     "**LeNet** was LeCun's CNN that recognized handwritten digits well enough to deploy commercially for document recognition — the canonical proof that the convolutional ideas plus gradient-based learning solve a real recognition problem end to end.",
     ["What problem did LeNet solve in production?"],
     ["Can connect LeNet to the deployed document-recognition breakthrough"], "core", "lecun/course-2#lesson-2.3")
node("build-lenet-mnist-classifier", "Build a LeNet-style MNIST classifier",
     "Reading is overrated. Build the thing LeCun built — a digit classifier — and train it yourself.",
     ("Course 2 project. A working MNIST classifier plus a written comparison to a modern architecture.\n\n"
      "```python\n"
      "# LeNet-style CNN on MNIST (PyTorch sketch)\n"
      "#  conv -> pool -> conv -> pool -> dense\n"
      "# 1. Data: MNIST, normalized\n"
      "# 2. Model: two conv+pool blocks, then dense head\n"
      "# 3. Train: forward pass -> loss -> backprop -> optimizer step\n"
      "# 4. Evaluate: accuracy on the test split\n"
      "```"),
     [], ["Trains a working MNIST classifier and reports test accuracy",
          "Writes a reasoned comparison to a modern architecture"], "apply",
     "lecun/course-2#lesson-2.4", kind="apply",
     apply=("Build and train a LeNet-style CNN on MNIST (conv -> pool -> conv -> pool -> dense) in PyTorch: "
            "normalize the data, define the network, run a training loop (forward pass, loss, backprop, "
            "optimizer step), and evaluate accuracy. A free Colab or local PyTorch environment is enough. "
            "Then write a short comparison to a modern architecture (e.g. a Vision Transformer): what "
            "assumptions does each bake in, and where does each win?"))
node("energy-based-models", "Energy-based models",
     "Instead of asking a model to output the answer, what if you ask it to score how well any answer fits — and pick the lowest-energy one?",
     "**Energy-based models** assign a scalar 'energy' to configurations of inputs and outputs, with low energy meaning compatible. Rather than predicting an output directly, you find the output that *minimizes* energy. This framing is the thread connecting LeCun's foundational work to his current world-model research.",
     ["What does an energy-based model score, and how is inference framed?"],
     ["Can explain energy as compatibility and inference as energy minimization"], "core", "lecun/course-2#lesson-2.5")

# ===== Course 3 — The Contrarian Bet ========================================
node("limits-of-autoregression", "The limits of autoregression",
     "If each word a model generates can be slightly wrong, what happens to the error over a long answer? LeCun thinks it's fatal.",
     "Autoregressive LLMs generate one token at a time, each conditioned on the last. LeCun argues errors compound across long generations and the approach lacks grounding in a world model — so scaling it alone won't reach human-level intelligence. This is the core of his anti-LLM thesis.",
     ["What is LeCun's core objection to autoregressive LLMs?"],
     ["Can state the error-accumulation / missing-world-model critique"], "core", "lecun/course-3#lesson-3.1")
node("self-supervised-learning", "Self-supervised learning",
     "Babies don't get labeled data. They learn the world by predicting what comes next — and LeCun thinks machines should too.",
     "**Self-supervised learning** trains models on unlabeled data by having them predict hidden or future parts of the input, learning rich representations without human labels. LeCun considers it the route to machines that build world models.",
     ["How does self-supervised learning get a training signal without labels?"],
     ["Can explain self-supervision via prediction of withheld input"], "core", "lecun/course-3#lesson-3.2")
node("autonomous-intelligence-blueprint", "The autonomous intelligence blueprint",
     "LeCun sketched an actual architecture for a machine that can perceive, predict, plan, and act — not a chatbot. Here's the blueprint.",
     "LeCun's blueprint for autonomous machine intelligence proposes modular components — perception, a **world model**, a cost/critic, an actor, and a configurator — arranged so the system can predict consequences and *plan* actions, rather than just map inputs to outputs.",
     ["What is the role of the world model in LeCun's blueprint?"],
     ["Can name the major modules and the perceive-predict-plan-act loop"], "core", "lecun/course-3#lesson-3.3")
node("jepa", "JEPA",
     "Predicting every pixel of the future is wasteful and nearly impossible. What if you predict in abstract representation space instead?",
     "A **Joint Embedding Predictive Architecture (JEPA)** predicts the *representation* of one part of an input from another, in an abstract embedding space rather than reconstructing raw pixels. It is an energy-based, self-supervised approach that learns what matters and ignores unpredictable detail.",
     ["What does a JEPA predict, and in what space?"],
     ["Can explain prediction in representation space vs pixel reconstruction"], "core", "lecun/course-3#lesson-3.4")
node("hierarchical-jepa", "Hierarchical JEPA",
     "Plans happen at many time scales — 'make coffee' vs 'lift the cup'. A single predictor can't do both. Stack them.",
     "**Hierarchical JEPA** stacks JEPA predictors at multiple levels of abstraction and time scale, so higher levels plan coarse, long-horizon steps and lower levels fill in fine-grained predictions — enabling hierarchical planning.",
     ["Why stack JEPA predictors hierarchically?"],
     ["Can explain multi-scale prediction and planning"], "core", "lecun/course-3#lesson-3.4")
node("jepa-model-lineage", "I-JEPA to V-JEPA 2 to LeJEPA",
     "The bet isn't just theory anymore. There's a growing line of working models.",
     "The JEPA idea has been instantiated in a lineage of models — I-JEPA (images), V-JEPA 2 (video), and LeJEPA — progressively extending joint-embedding predictive learning to richer modalities and turning the thesis into trainable systems.",
     ["Name two models in the JEPA lineage and their modality."],
     ["Can trace the I-JEPA -> V-JEPA 2 -> LeJEPA progression"], "core", "lecun/course-3#lesson-3.5")
node("ami-labs-the-live-bet", "AMI Labs: the live bet",
     "LeCun left a top industrial lab to actually build this. The contrarian bet is now a live company.",
     "LeCun's move to pursue autonomous machine intelligence through a dedicated startup (AMI Labs) is the real-world wager: leaving a major lab to chase world-model research the rest of the field is largely not pursuing. It is the present-tense continuation of the 1980s connectionist bet.",
     ["What is the significance of LeCun starting AMI Labs?"],
     ["Can connect the startup to the long-horizon conviction theme"], "core", "lecun/course-3#lesson-3.6")
node("apply-llms-vs-world-models-debate", "Defend a position: LLMs vs. world models",
     "Pick a side and defend it: are LLMs a detour, or is LeCun overconfident? Argue it.",
     "Course 3 project. A defended position in the 'LLMs vs. world models' debate.",
     [], ["Defends a position with evidence and steelmans the opposition"], "apply",
     "lecun/course-3#project", kind="apply",
     apply=("Take and defend a position in the 'LLMs vs. world models' debate. Use the autoregression "
            "critique, self-supervised learning, and JEPA as evidence; steelman the opposing view before "
            "rebutting it. Assessed on reasoning, not the side you take."))

# ===== Person anchor (Phase 5 §7) — the hub the three spines hang off ========
node("person-yann-lecun", "Yann LeCun",
     "The man who bet his career on machines that learn — and is now betting it again, against the grain, on world models.",
     "Yann LeCun is a French-American computer scientist, a pioneer of convolutional networks and "
     "gradient-based learning, Chief AI Scientist at Meta (2013–2025), NYU professor, and co-recipient of "
     "the 2018 Turing Award. His career is a single long wager that learning from data — not hand-coded "
     "rules — is the road to machine intelligence.",
     [], [], "intro", "lecun/person", kind="person",
     attributes={"born": 1960, "country": "France",
                 "affiliations": ["Bell Labs", "NYU", "Meta", "AMI Labs"],
                 "notable_for": ["convolutional networks", "backpropagation in practice",
                                 "energy-based models", "JEPA / world models"],
                 "awards": ["2018 Turing Award", "Legion of Honour"]})

# --- edges -------------------------------------------------------------------
E = []
def edge(src, dst, typ, origin="authored", w=1.0):
    E.append({"id": nid(f"edge:{src}->{dst}:{typ}"),
              "src_node": nid(src), "dst_node": nid(dst),
              "type": typ, "weight": w, "origin": origin})

spine1 = ["connectionism-vs-symbolic-ai","lecuns-connectionist-bet","ai-winter",
          "why-neural-nets-stalled","early-vs-wrong","bell-labs-and-the-deployed-cnn",
          "the-deep-learning-trio","the-2012-inflection","building-fair-institution",
          "lecuns-honors-and-legacy","lecun-as-public-voice","apply-conviction-driven-research"]
spine2 = ["loss-and-gradient-descent","backpropagation","end-to-end-learning",
          "the-convolutional-network","cnn-local-receptive-fields","cnn-weight-sharing",
          "cnn-pooling","lenet-and-document-recognition","build-lenet-mnist-classifier",
          "energy-based-models"]
spine3 = ["limits-of-autoregression","self-supervised-learning","autonomous-intelligence-blueprint",
          "jepa","hierarchical-jepa","jepa-model-lineage","ami-labs-the-live-bet",
          "apply-llms-vs-world-models-debate"]

for s in (spine1, spine2, spine3):
    for a, b in zip(s, s[1:]):
        edge(a, b, "next_in_spine")

# the convolutional sub-concepts elaborate the integrating node
for sub in ("cnn-local-receptive-fields","cnn-weight-sharing","cnn-pooling"):
    edge(sub, "the-convolutional-network", "elaborates")
# the build exercises the concepts it applies
for c in ("the-convolutional-network","backpropagation","loss-and-gradient-descent","lenet-and-document-recognition"):
    edge("build-lenet-mnist-classifier", c, "applies")
# the cross-course prerequisite the author specified explicitly, plus a second feeder
edge("jepa", "energy-based-models", "prerequisite")        # C3.4 leans on C2.5
edge("jepa", "self-supervised-learning", "prerequisite")
edge("hierarchical-jepa", "jepa", "prerequisite")
edge("jepa-model-lineage", "jepa", "prerequisite")
# lateral threads (rabbit holes) the narrative sets up across courses
edge("lecuns-connectionist-bet", "backpropagation", "rabbit_hole")     # 1.1 teases backprop -> C2
edge("lecun-as-public-voice", "limits-of-autoregression", "rabbit_hole") # 1.5 sets up C3
# contrast that powers the debate
edge("jepa", "limits-of-autoregression", "contrasts")
# Phase 5 §7: the three spine signature nodes are ABOUT the person — the pilot
# now reads as one Person-anchored subgraph hanging off person-yann-lecun.
for sig in ("the-convolutional-network", "jepa", "lecuns-connectionist-bet"):
    edge(sig, "person-yann-lecun", "about")

# --- spines ------------------------------------------------------------------
def spine(key, title, subject, seq, desc):
    return {"id": nid(f"spine:{key}"), "title": title, "subject": subject,
            "description": desc, "origin": "authored",
            "node_sequence": [nid(k) for k in seq], "source_ref": "lecun-course/"}
S = [
    spine("conviction", "The Conviction", "Understanding Yann LeCun", spine1,
          "Career, history, temperament — narrative scaffolding for the path."),
    spine("foundations", "The Foundations", "Understanding Yann LeCun", spine2,
          "CNNs, backprop, energy-based models — the hands-on technical core."),
    spine("contrarian-bet", "The Contrarian Bet", "Understanding Yann LeCun", spine3,
          "World models, JEPA, the anti-LLM thesis — the frontier."),
]

out = {"sources": [SOURCE], "nodes": N, "edges": E, "spines": S}
with open("lecun_seed_graph.json", "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)

print(f"nodes={len(N)}  edges={len(E)}  spines={len(S)}")
# sanity: every edge endpoint and spine member must be a real node
keys = {n["id"] for n in N}
bad = [e for e in E if e["src_node"] not in keys or e["dst_node"] not in keys]
miss = [k for s in S for k in s["node_sequence"] if k not in keys]
assert not bad,  f"dangling edges: {bad}"
assert not miss, f"spine refers to missing nodes: {miss}"
print("validation OK — no dangling edges, no missing spine members")
