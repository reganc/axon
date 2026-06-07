"""content seam — canonical graph CRUD. Phase 1."""


class StubContent:
    async def upsert_node(self, node): raise NotImplementedError("content seam — Phase 1")
    async def add_edge(self, src, dst, type, origin, weight=1.0): raise NotImplementedError("content seam — Phase 1")
    async def get_subgraph(self, node_ids, depth=1): raise NotImplementedError("content seam — Phase 1")
    async def get_spine(self, spine_id): raise NotImplementedError("content seam — Phase 1")
