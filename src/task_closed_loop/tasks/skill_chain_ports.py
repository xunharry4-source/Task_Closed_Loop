"""Reasoner contract for the first step (project chain). Separate from the legacy port.

`generation_ports.TaskGenerationReasonerPort` keeps describing the discovery->seed->
candidate chain used by the task-only runtime. The locked pipeline's Stage 3 uses the
chain below instead; both are satisfied by the same adapters.
"""

from __future__ import annotations

from typing import Any, Protocol

from task_closed_loop.integration.models import CapabilityDescriptor, ResourceSnapshot
from task_closed_loop.tasks.models import TaskCandidate
from task_closed_loop.tasks.skill_chain_models import (
    DemandRecord,
    ProblemRecord,
    ThemePlan,
    ValueRecord,
)


class ProjectChainReasonerPort(Protocol):
    """Three independent discovery steps, then themes, then one call per theme.

    Problems, values and demands are siblings: each is derived from the project's own
    resources and functions, and none reads another's conclusions — chaining them would
    let one step's blind spot become the next step's starting point. Themes then read
    all three. The task step sees only resources, functions, the project and one theme,
    so a task inherits its lineage from that theme.
    """

    async def discover_project_problems(
        self,
        project: dict[str, Any],
        resources: list[ResourceSnapshot],
        capabilities: list[CapabilityDescriptor],
        existing_tasks: list[Any],
    ) -> list[ProblemRecord]:
        ...

    async def discover_project_values(
        self,
        project: dict[str, Any],
        resources: list[ResourceSnapshot],
        capabilities: list[CapabilityDescriptor],
        existing_tasks: list[Any],
    ) -> list[ValueRecord]:
        ...

    async def discover_project_demands(
        self,
        project: dict[str, Any],
        resources: list[ResourceSnapshot],
        capabilities: list[CapabilityDescriptor],
    ) -> list[DemandRecord]:
        ...

    async def plan_project_themes(
        self,
        project: dict[str, Any],
        resources: list[ResourceSnapshot],
        capabilities: list[CapabilityDescriptor],
        problems: list[ProblemRecord],
        values: list[ValueRecord],
        demands: list[DemandRecord],
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
        resources: list[ResourceSnapshot],
        capabilities: list[CapabilityDescriptor],
        existing_tasks: list[Any],
    ) -> list[TaskCandidate]:
        """Tasks of one theme. Lineage is attached by the Host from the theme."""
        ...
