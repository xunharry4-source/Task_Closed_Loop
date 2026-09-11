from __future__ import annotations

from typing import Protocol

from task_closed_loop.integration.models import CapabilityDescriptor
from task_closed_loop.reality.models import RealitySnapshot
from task_closed_loop.tasks.generation_models import (
    CandidateReview,
    CandidateSetReview,
    FinalTaskRealityReview,
)
from task_closed_loop.tasks.models import Task, TaskCandidate


class TaskGenerationReasonerPort(Protocol):
    async def discover_task_candidates(
        self,
        reality: RealitySnapshot,
        existing_tasks: list[Task],
        capabilities: list[CapabilityDescriptor],
    ) -> list[TaskCandidate]:
        ...

    async def destructive_review_candidate(
        self,
        reality: RealitySnapshot,
        candidate: TaskCandidate,
        existing_tasks: list[Task],
        capabilities: list[CapabilityDescriptor],
    ) -> CandidateReview:
        ...

    async def destructive_review_candidate_set(
        self,
        reality: RealitySnapshot,
        candidates: list[TaskCandidate],
        existing_tasks: list[Task],
    ) -> CandidateSetReview:
        ...

    async def review_final_task_reality(
        self,
        reality: RealitySnapshot,
        task: Task,
    ) -> FinalTaskRealityReview:
        ...
