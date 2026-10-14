"""Reasoner contract for the first step (project chain). Separate from the legacy port.

`generation_ports.TaskGenerationReasonerPort` keeps describing the discovery->seed->
candidate chain used by the task-only runtime. The locked pipeline's Stage 3 uses the
chain below instead; both are satisfied by the same adapters.
"""

from __future__ import annotations

from typing import Any, Protocol

from task_closed_loop.integration.models import CapabilityDescriptor, ResourceSnapshot
from task_closed_loop.reality.models import RealitySnapshot
from task_closed_loop.tasks.models import TaskCandidate
from task_closed_loop.tasks.skill_chain_models import (
    DemandRecord,
    ProblemRecord,
    ThemePlan,
    ValueRecord,
)


class ProjectChainReasonerPort(Protocol):
    """Four independent discovery steps, then one call per theme.

    Problems, values, demands and themes are siblings: each is derived from the
    project's own resources, reality and capabilities, and none of them reads another's
    conclusions. Chaining them would let one step's blind spot become the next step's
    starting point. Only the per-theme task call sees all three middle layers, because
    that is where a task picks the source record it comes from.
    """

    async def discover_project_problems(
        self,
        project: dict[str, Any],
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        capabilities: list[CapabilityDescriptor],
        existing_tasks: list[Any],
    ) -> list[ProblemRecord]:
        ...

    async def discover_project_values(
        self,
        project: dict[str, Any],
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        capabilities: list[CapabilityDescriptor],
        existing_tasks: list[Any],
    ) -> list[ValueRecord]:
        ...

    async def discover_project_demands(
        self,
        project: dict[str, Any],
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        capabilities: list[CapabilityDescriptor],
    ) -> list[DemandRecord]:
        ...

    async def plan_project_themes(
        self,
        project: dict[str, Any],
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        capabilities: list[CapabilityDescriptor],
        fixed_themes: list[str],
        previous_theme_yield: dict[str, int],
    ) -> ThemePlan:
        ...

    async def generate_theme_tasks(
        self,
        project: dict[str, Any],
        theme: str,
        theme_kind: str,
        theme_instruction: str,
        resource_info: str,
        capability_info: str,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        capabilities: list[CapabilityDescriptor],
        problems: list[ProblemRecord],
        values: list[ValueRecord],
        demands: list[DemandRecord],
        existing_tasks: list[Any],
    ) -> list[tuple[TaskCandidate, str, str]]:
        """Returns (candidate, source_kind, source_ref_id) triples."""
        ...
