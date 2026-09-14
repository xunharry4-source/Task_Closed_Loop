from __future__ import annotations
from task_closed_loop.contracts import TaskDraftBatch

class LlmTaskRegenerator:
    def __init__(self, *, runtime_provider):
        self.runtime_provider = runtime_provider

    async def regenerate(self, *, base_batch, current_tasks, accepted_candidates, dimensions, round_number: int) -> TaskDraftBatch:
        components = await self.runtime_provider.validate_task()
        prepared = base_batch.prepared
        current_existing = list(prepared.effective_existing_tasks) + list(current_tasks)
        current_all = list(prepared.all_existing_tasks) + list(current_tasks)
        draft = await components.orchestrator.task_generation.generate_drafts(
            reality=prepared.reality,
            existing_tasks=current_existing,
            all_existing_tasks=current_all,
            task_outcomes=list(prepared.task_outcomes),
            consumed_outcome_ids=list(prepared.consumed_outcome_ids),
            capabilities=list(prepared.capabilities),
            resources=list(prepared.resources),
            thinking_dimensions=list(dimensions),
            prior_accepted_candidates=list(accepted_candidates),
        )
        return TaskDraftBatch(
            prepared=prepared,
            draft=draft,
            existing_tasks=tuple(current_existing),
            all_existing_tasks=tuple(current_all),
            round_number=round_number,
            source_stage=7,
        )
