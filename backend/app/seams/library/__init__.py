"""library seam — semantic search, spine assembly, checkout/overlay. Phase 1."""


class StubLibrary:
    async def search(self, query, k=10): raise NotImplementedError("library seam — Phase 1")
    async def coverage(self, subject): raise NotImplementedError("library seam — Phase 1")
    async def checkout(self, user_id, spine_id, subject): raise NotImplementedError("library seam — Phase 1")
    async def overlay_state(self, checkout_id): raise NotImplementedError("library seam — Phase 1")
