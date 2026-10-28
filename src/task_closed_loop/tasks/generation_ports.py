from __future__ import annotations

from typing import Protocol

from task_closed_loop.integration.models import (
    CapabilityDescriptor,
    ResourceSnapshot,
)
from task_closed_loop.reality.models import (
    RealitySnapshot,
)
from task_closed_loop.tasks.generation_models import (
    CandidateFailureContext,
    CandidateFieldRepair,
    CandidateFieldReview,
    CandidateReview,
    DiscoverySignal,
    CandidateSetReview,
    CoverageDimension,
    FinalTaskRealityReview,
    TaskOutcomeRecord,
    TaskSeed,
)
from task_closed_loop.tasks.models import (
    Task,
    TaskCandidate,
)


class TaskGenerationReasonerPort(
    Protocol
):

    async def discover_need_opportunities(
        self,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        existing_tasks: list[Task],
        all_existing_tasks: list[Task],
        capabilities: list[
            CapabilityDescriptor
        ],
    ) -> list[DiscoverySignal]:
        ...

    async def discover_task_proliferation_seeds(
        self,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        existing_tasks: list[Task],
        all_existing_tasks: list[Task],
        capabilities: list[
            CapabilityDescriptor
        ],
        task_outcomes: list[TaskOutcomeRecord],
    ) -> list[TaskSeed]:
        ...
    async def discover_task_candidates(
        self,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        existing_tasks: list[Task],
        capabilities: list[
            CapabilityDescriptor
        ],
        thinking_dimensions: list[
            CoverageDimension
        ] | None = None,
        accepted_candidates: list[
            TaskCandidate
        ] | None = None,
    ) -> list[TaskCandidate]:
        ...

    async def discover_task_seeds(
        self,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        existing_tasks: list[Task],
        capabilities: list[
            CapabilityDescriptor
        ],
        thinking_dimensions: list[
            CoverageDimension
        ] | None = None,
        accepted_candidates: list[
            TaskCandidate
        ] | None = None,
        discovery_signals: list[
            DiscoverySignal
        ] | None = None,
    ) -> list[TaskSeed]:
        ...

    async def materialize_task_candidates(
        self,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        existing_tasks: list[Task],
        capabilities: list[
            CapabilityDescriptor
        ],
        seeds: list[TaskSeed],
        accepted_candidates: list[
            TaskCandidate
        ] | None = None,
    ) -> list[TaskCandidate]:
        ...

    async def repair_candidate_fields(
        self,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        existing_tasks: list[Task],
        capabilities: list[
            CapabilityDescriptor
        ],
        candidate: TaskCandidate,
        field_issues: list[str],
    ) -> CandidateFieldRepair:
        ...

    async def expand_thinking_dimensions(
        self,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        existing_tasks: list[Task],
        capabilities: list[
            CapabilityDescriptor
        ],
        accepted_candidates: list[
            TaskCandidate
        ],
        rejected_contexts: list[
            CandidateFailureContext
        ] | None = None,
    ) -> list[CoverageDimension]:
        ...

    async def destructive_review_candidate(
        self,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        candidate: TaskCandidate,
        existing_tasks: list[Task],
        capabilities: list[
            CapabilityDescriptor
        ],
    ) -> CandidateReview:
        """Single-candidate core validity only (is the work relation real)."""
        ...

    async def review_candidate_fields(
        self,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        candidate: TaskCandidate,
        existing_tasks: list[Task],
        capabilities: list[
            CapabilityDescriptor
        ],
    ) -> CandidateFieldReview:
        """Single-candidate field quality; call only after core validity passes."""
        ...

    async def destructive_review_candidate_set(
        self,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        candidates: list[
            TaskCandidate
        ],
        existing_tasks: list[Task],
        capabilities: list[
            CapabilityDescriptor
        ],
    ) -> CandidateSetReview:
        ...

    async def review_final_task_reality(
        self,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        capabilities: list[
            CapabilityDescriptor
        ],
        task: Task,
    ) -> FinalTaskRealityReview:
        ...
