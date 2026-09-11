from task_closed_loop.llm.ports import RealityReasonerPort
from .models import RealityBuildInput

class RealityEngine:
    def __init__(self, reasoner: RealityReasonerPort): self._reasoner=reasoner
    async def build(self, data: RealityBuildInput):
        return await self._reasoner.build_reality(data)
