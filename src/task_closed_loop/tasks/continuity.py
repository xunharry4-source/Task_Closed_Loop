class TaskContinuityEngine:
    def __init__(self, reasoner): self._reasoner=reasoner
    async def evaluate(self, reality, existing_tasks):
        return await self._reasoner.evaluate_existing_tasks(reality, existing_tasks)
