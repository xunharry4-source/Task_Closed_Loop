from __future__ import annotations

from typing import Protocol

from task_closed_loop.reality.models import RealityBuildInput, RealitySnapshot
from task_closed_loop.tasks.models import Task


class RealityReasonerPort(Protocol):
    async def build_reality(
        self,
        data: RealityBuildInput,
    ) -> RealitySnapshot:
        ...


class TaskContinuityReasonerPort(Protocol):
    async def evaluate_existing_tasks(
        self,
        reality: RealitySnapshot,
        existing_tasks: list[Task],
    ) -> list[Task]:
        ...
