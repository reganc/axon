"""ingestion seam — canonicalization core + seed loader (P1) + transcript miner (P3)."""


class StubIngestion:
    def __init__(self, llm=None, content=None):
        self.llm, self.content = llm, content

    async def canonicalize(self, candidate): raise NotImplementedError("ingestion seam — Phase 1")
    async def ingest_seed(self, path): raise NotImplementedError("ingestion seam — Phase 1")
    async def mine(self, source_kind, path): raise NotImplementedError("ingestion seam — Phase 3")
