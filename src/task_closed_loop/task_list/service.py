from __future__ import annotations

from task_closed_loop.reality.builder import (
    RealityEngine,
)
from task_closed_loop.reality.models import (
    RealityBuildInput,
)
from task_closed_loop.task_list.models import (
    TaskListInputError,
    TaskListItem,
    TaskListRequest,
    TaskListResult,
)
from task_closed_loop.tasks.generator import (
    TaskGenerationEngine,
)


class TaskListService:
    """
    JSON-friendly facade over the same Task Generation Core.

    It does not define a second task-generation system.
    """

    def __init__(
        self,
        task_reasoner,
        audit_reasoner,
        *,
        coverage_expansion_min_tasks: int = 5,
    ):
        self._reality = RealityEngine(
            task_reasoner
        )
        self._generation = (
            TaskGenerationEngine(
                task_reasoner=(
                    task_reasoner
                ),
                audit_reasoner=(
                    audit_reasoner
                ),
                coverage_expansion_min_tasks=(
                    coverage_expansion_min_tasks
                ),
            )
        )

    async def generate(
        self,
        request: TaskListRequest,
    ) -> TaskListResult:
        if not isinstance(
            request,
            TaskListRequest,
        ):
            raise TaskListInputError(
                "TaskListService.generate "
                "只接受 TaskListRequest。"
            )

        resources = list(
            request.resources
        )
        capabilities = list(
            request.capabilities
        )

        reality = await (
            self._reality.build(
                RealityBuildInput(
                    resources=resources,
                )
            )
        )

        generation = await (
            self._generation.generate(
                resources=resources,
                reality=reality,
                existing_tasks=[],
                capabilities=(
                    capabilities
                ),
            )
        )

        return TaskListResult(
            tasks=tuple(
                TaskListItem.from_task(
                    task
                )
                for task
                in generation.tasks
            ),
            generation=generation,
        )

    async def generate_from_payload(
        self,
        payload,
    ) -> TaskListResult:
        return await self.generate(
            TaskListRequest.from_payload(
                payload
            )
        )
