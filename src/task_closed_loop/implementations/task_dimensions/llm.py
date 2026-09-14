from __future__ import annotations
from task_closed_loop.contracts import TaskDimensionResult

class LlmTaskDimensionGenerator:
    def __init__(self, *, runtime_provider):
        self.runtime_provider = runtime_provider

    async def generate(self, *, base_batch, audit_result, accepted_candidates, round_number: int) -> TaskDimensionResult:
        components = await self.runtime_provider.validate_task()
        expand = getattr(components.task_llm, "expand_thinking_dimensions", None)
        if not callable(expand):
            return TaskDimensionResult(dimensions=(), round_number=round_number)
        dimensions = list(await expand(
            resources=list(base_batch.prepared.resources),
            reality=base_batch.prepared.reality,
            existing_tasks=list(base_batch.prepared.effective_existing_tasks),
            capabilities=list(base_batch.prepared.capabilities),
            accepted_candidates=list(accepted_candidates),
            rejected_contexts=list(audit_result.generation.trace.rejected_candidate_contexts),
        ) or [])
        return TaskDimensionResult(dimensions=tuple(dimensions), round_number=round_number)
