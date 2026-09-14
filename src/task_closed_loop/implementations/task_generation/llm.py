from __future__ import annotations

from dataclasses import replace

from task_closed_loop.app.orchestrator import RuntimeCycleInput
from task_closed_loop.contracts import TaskDraftBatch


def _production_capabilities(capabilities):
    """Disable legacy Observation Acquisition inside the locked production pipeline.

    Stage 2 is now the mandatory reality-acquisition/materialization stage.  Entering
    Stage 3 with ``can_observe_state=True`` would cause the legacy TaskGenerationEngine
    to create another observation parent for Gmail/DB/Drive/etc. even though Stage 2
    has already queried that surface.  The capability remains available for business
    execution; only the *Task-generation observation trigger* is disabled here.

    Task-only / lifecycle runtimes that intentionally bypass Stage 2 still use the
    original capability descriptors and retain Observation Acquisition behavior.
    """

    return [
        replace(capability, can_observe_state=False)
        if getattr(capability, "can_observe_state", False)
        else capability
        for capability in capabilities
    ]


class LlmInitialTaskGenerator:
    def __init__(self, *, runtime_provider):
        self.runtime_provider = runtime_provider

    async def generate(self, resources, capabilities) -> TaskDraftBatch:
        components = await self.runtime_provider.validate_task()
        orchestrator = components.orchestrator
        prepared = await orchestrator.prepare_context(
            RuntimeCycleInput(
                resources=list(resources),
                capabilities=_production_capabilities(capabilities),
                existing_tasks=[],
            )
        )
        draft = await orchestrator.task_generation.generate_drafts(
            reality=prepared.reality,
            existing_tasks=list(prepared.effective_existing_tasks),
            all_existing_tasks=list(prepared.all_existing_tasks),
            task_outcomes=list(prepared.task_outcomes),
            consumed_outcome_ids=list(prepared.consumed_outcome_ids),
            capabilities=list(prepared.capabilities),
            resources=list(prepared.resources),
        )
        return TaskDraftBatch(
            prepared=prepared,
            draft=draft,
            existing_tasks=tuple(prepared.effective_existing_tasks),
            all_existing_tasks=tuple(prepared.all_existing_tasks),
            round_number=0,
            source_stage=3,
        )
