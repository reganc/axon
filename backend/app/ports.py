"""
ports.py — the seams.

Every cross-seam call goes through one of these Protocols; a seam may import a
*port*, never another seam's internals. DTOs are Pydantic models so they also
serialize over the API and the WebSocket for free.

Implementations live in app/seams/<name>/. Phase 0 ships stubs that raise
NotImplementedError (surfaced as HTTP 501); later phases replace them.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------
Role = Literal["learner", "author", "admin"]
# Phase 5: node type is first-class. concept/apply are the originals; the rest
# generalize the graph (a question is a generation seed, a person is a hub, …).
NodeKind = Literal[
    "concept", "apply", "question", "person", "artifact", "project", "skill"
]
EdgeType = Literal[
    "next_in_spine",
    "prerequisite",
    "elaborates",
    "applies",
    "contrasts",
    "rabbit_hole",
    # Phase 5 relationship types
    "authored_by",
    "about",
    "answers",
    "inspired_by",
    "contradicts",
    "teaches",
]
Origin = Literal["authored", "ai_generated", "ai_extended"]
Tier = Literal["fast", "reason"]


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------
class Principal(BaseModel):
    user_id: UUID
    role: Role


class NodeIn(BaseModel):
    canonical_key: str
    title: str
    kind: NodeKind = "concept"
    hook: str | None = None
    body: str | None = None
    apply_prompt: str | None = None
    recall_prompts: list[str] = Field(default_factory=list)
    mastery_criteria: list[str] = Field(default_factory=list)
    depth_level: str | None = None
    origin: Origin = "ai_generated"
    locked: bool = False
    source_ref: str | None = None
    confidence: float = 0.5
    attributes: dict = Field(default_factory=dict)  # Phase 5: type-specific data


class Node(NodeIn):
    id: UUID
    version: int = 1


class Edge(BaseModel):
    id: UUID | None = None
    src_node: UUID
    dst_node: UUID
    type: EdgeType
    weight: float = 1.0
    origin: str = "authored"


class Subgraph(BaseModel):
    nodes: list[Node]
    edges: list[Edge]


class SpineWithNodes(BaseModel):
    id: UUID
    title: str
    subject: str
    nodes: list[Node]


class SpineSummary(BaseModel):
    id: UUID
    title: str
    subject: str
    description: str | None = None
    node_count: int = 0


# Phase 5 §8: a browse hierarchy *derived* from current graph contents (a view,
# not a stored tree). Each dimension's values are computed live and change as the
# graph grows.
class FacetValue(BaseModel):
    label: str
    node_count: int
    sample_titles: list[str] = Field(default_factory=list)


class FacetGroup(BaseModel):
    dimension: str  # "type" | "origin" | "subject" | "theme"
    values: list[FacetValue]


class Facets(BaseModel):
    node_total: int
    groups: list[FacetGroup]


class ScoredNode(BaseModel):
    node: Node
    score: float


class Coverage(BaseModel):
    subject: str
    have: list[UUID] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class Checkout(BaseModel):
    id: UUID
    user_id: UUID
    spine_id: UUID | None = None
    subject: str | None = None


class CheckoutSummary(BaseModel):
    id: UUID
    subject: str | None = None
    spine_id: UUID | None = None
    spine_title: str | None = None
    created_at: datetime
    last_activity: datetime | None = None
    message_count: int = 0


class ConversationEvent(BaseModel):
    type: str
    data: dict = Field(default_factory=dict)


class NodeState(BaseModel):
    checkout_id: UUID
    node_id: UUID
    mastery: float = 0.0
    next_review_at: datetime | None = None
    learner_notes: str | None = None


class CandidateNode(BaseModel):
    title: str
    kind: NodeKind = "concept"  # study materials persist as artifact/question nodes
    hook: str | None = None
    body: str | None = None
    recall_prompts: list[str] = Field(default_factory=list)
    origin: Origin = "ai_generated"
    source_ref: str | None = None
    confidence: float = 0.5  # set by the Researcher; carried into the persisted node


class CanonResult(BaseModel):
    node: Node
    action: Literal["created", "merged"]
    neighbor_id: UUID | None = None


class IngestReport(BaseModel):
    nodes: int = 0
    edges: int = 0
    spines: int = 0
    merged: int = 0
    redacted: int = 0


class InteractionEvent(BaseModel):
    checkout_id: UUID
    node_id: UUID | None = None
    event_type: str
    payload: dict = Field(default_factory=dict)
    ts: datetime | None = None


class Msg(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class StreamEvent(BaseModel):
    # The one stream the Tutor produces; the frontend demuxes into voice + canvas.
    type: Literal[
        "say", "ask", "node.create", "node.update", "edge.create", "status", "done"
    ]
    data: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------
@runtime_checkable
class AuthPort(Protocol):
    def issue_token(self, user_id: UUID, role: Role) -> str: ...
    def verify(self, token: str) -> Principal: ...
    def require(self, principal: Principal, perm: str) -> None: ...


@runtime_checkable
class ContentPort(Protocol):
    async def upsert_node(self, node: NodeIn) -> Node: ...
    async def add_edge(
        self, src: UUID, dst: UUID, type: EdgeType, origin: str, weight: float = 1.0
    ) -> Edge: ...
    async def get_subgraph(self, node_ids: list[UUID], depth: int = 1) -> Subgraph: ...
    async def get_spine(self, spine_id: UUID) -> SpineWithNodes: ...


@runtime_checkable
class LibraryPort(Protocol):
    async def search(self, query: str, k: int = 10) -> list[ScoredNode]: ...
    async def coverage(self, subject: str) -> Coverage: ...
    async def checkout(
        self, user_id: UUID, spine_id: UUID | None, subject: str | None
    ) -> Checkout: ...
    async def overlay_state(self, checkout_id: UUID) -> list[NodeState]: ...


@runtime_checkable
class LearningPort(Protocol):
    async def record(self, event: InteractionEvent) -> None: ...
    async def update_mastery(self, checkout_id: UUID, node_id: UUID) -> float: ...
    async def due_reviews(self, checkout_id: UUID) -> list[UUID]: ...


@runtime_checkable
class LLMPort(Protocol):
    # routes fast -> Ollama (local, RTX 3060), reason -> Anthropic API
    def stream(self, msgs: list[Msg], tier: Tier) -> AsyncIterator[str]: ...
    async def complete(self, msgs: list[Msg], tier: Tier) -> str: ...
    async def embed(self, text: str) -> list[float]: ...  # 768-dim


@runtime_checkable
class CompanionPort(Protocol):
    def run_turn(
        self, checkout_id: UUID, message: str
    ) -> AsyncIterator[StreamEvent]: ...
    def pull_thread(
        self, checkout_id: UUID, node_id: UUID
    ) -> AsyncIterator[StreamEvent]: ...
    def explain_node(
        self, checkout_id: UUID, node_id: UUID
    ) -> AsyncIterator[StreamEvent]: ...


@runtime_checkable
class IngestionPort(Protocol):
    async def canonicalize(self, candidate: CandidateNode) -> CanonResult: ...
    async def ingest_seed(self, path: str) -> IngestReport: ...
    async def mine(self, source_kind: str, path: str) -> IngestReport: ...
