"""companion seam — agents (Planner/Tutor/Researcher/Librarian) + LLM gateway. Phase 2."""


class StubLLM:
    async def stream(self, msgs, tier): raise NotImplementedError("LLM gateway — Phase 2")
    async def complete(self, msgs, tier): raise NotImplementedError("LLM gateway — Phase 2")
    async def embed(self, text): raise NotImplementedError("LLM gateway — Phase 2")


class StubCompanion:
    def __init__(self, llm=None, library=None):
        self.llm, self.library = llm, library

    async def run_turn(self, checkout_id, message): raise NotImplementedError("companion seam — Phase 2")
    async def pull_thread(self, checkout_id, node_id): raise NotImplementedError("companion seam — Phase 2")
