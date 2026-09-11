from __future__ import annotations

from dataclasses import dataclass, field

from task_closed_loop.integration.models import ResourceRef
from task_closed_loop.reality.models import RealityBuildInput
from task_closed_loop.tasks.generation_models import TaskGenerationResult


@dataclass
class RuntimeCycleInput:
    existing_tasks: list = field(default_factory=list)
    evidence: list = field(default_factory=list)
    external_effects: list = field(default_factory=list)
    execution_deltas: list = field(default_factory=list)
    related_history: list = field(default_factory=list)


@dataclass
class RuntimeCycleResult:
    reality: object
    effective_existing_tasks: list
    task_generation: TaskGenerationResult

    @property
    def new_tasks(self):
        return self.task_generation.tasks

    @property
    def new_task_candidates(self):
        return self.task_generation.accepted_candidates


class RuntimeOrchestrator:
    def __init__(
        self,
        registry,
        reality_engine,
        task_continuity,
        task_generation,
    ):
        self.registry = registry
        self.reality_engine = reality_engine
        self.task_continuity = task_continuity
        self.task_generation = task_generation

    async def run_cycle(self, data):
        descriptors = await self.registry.discover_resources()
        resources = [
            await self.registry.read_resource(
                ResourceRef(
                    descriptor.provider_id,
                    descriptor.resource_id,
                )
            )
            for descriptor in descriptors
        ]

        capabilities = await self.registry.discover_capabilities()

        reality = await self.reality_engine.build(
            RealityBuildInput(
                resources=resources,
                evidence=data.evidence,
                external_effects=data.external_effects,
                execution_deltas=data.execution_deltas,
                related_history=data.related_history,
            )
        )

        effective = await self.task_continuity.evaluate(
            reality,
            data.existing_tasks,
        )

        generation = await self.task_generation.generate(
            reality,
            effective,
            capabilities,
        )

        return RuntimeCycleResult(
            reality=reality,
            effective_existing_tasks=effective,
            task_generation=generation,
        )
