from __future__ import annotations

from task_closed_loop.integration.models import CapabilityDescriptor
from task_closed_loop.reality.models import RealitySnapshot
from task_closed_loop.tasks.finalizer import (
    DeterministicTaskFinalizer,
    FinalizerFidelityAudit,
)
from task_closed_loop.tasks.generation_audit import (
    CandidateSetStructuralAudit,
    CandidateStructuralAudit,
)
from task_closed_loop.tasks.generation_models import (
    TaskGenerationResult,
    TaskGenerationTrace,
)
from task_closed_loop.tasks.generation_ports import TaskGenerationReasonerPort
from task_closed_loop.tasks.models import Task
from task_closed_loop.tasks.reality_validity import TaskRealityValidityAudit


class TaskGenerationEngine:
    def __init__(
        self,
        reasoner: TaskGenerationReasonerPort,
        candidate_audit: CandidateStructuralAudit | None = None,
        set_audit: CandidateSetStructuralAudit | None = None,
        finalizer: DeterministicTaskFinalizer | None = None,
        fidelity_audit: FinalizerFidelityAudit | None = None,
        reality_validity_audit: TaskRealityValidityAudit | None = None,
    ):
        self._reasoner = reasoner
        self._candidate_audit = candidate_audit or CandidateStructuralAudit()
        self._set_audit = set_audit or CandidateSetStructuralAudit()
        self._finalizer = finalizer or DeterministicTaskFinalizer()
        self._fidelity_audit = fidelity_audit or FinalizerFidelityAudit()
        self._reality_validity_audit = (
            reality_validity_audit or TaskRealityValidityAudit()
        )

    async def generate(
        self,
        reality: RealitySnapshot,
        existing_tasks: list[Task],
        capabilities: list[CapabilityDescriptor],
    ) -> TaskGenerationResult:
        trace = TaskGenerationTrace()

        discovered = await self._reasoner.discover_task_candidates(
            reality=reality,
            existing_tasks=existing_tasks,
            capabilities=capabilities,
        )
        trace.discovered_candidate_ids = [
            candidate.candidate_id for candidate in discovered
        ]

        individually_accepted = []

        for candidate in discovered:
            structural = self._candidate_audit.review(
                reality=reality,
                candidate=candidate,
                existing_tasks=existing_tasks,
                capabilities=capabilities,
            )
            trace.structural_findings.extend(structural)

            semantic = await self._reasoner.destructive_review_candidate(
                reality=reality,
                candidate=candidate,
                existing_tasks=existing_tasks,
                capabilities=capabilities,
            )
            trace.candidate_reviews.append(semantic)

            if not structural and semantic.keep:
                individually_accepted.append(candidate)

        deduped, set_structural = self._set_audit.deduplicate(
            individually_accepted
        )
        trace.structural_findings.extend(set_structural)

        set_review = await self._reasoner.destructive_review_candidate_set(
            reality=reality,
            candidates=deduped,
            existing_tasks=existing_tasks,
        )
        trace.set_review = set_review

        keep_ids = set(set_review.keep_candidate_ids)
        set_accepted = [
            candidate
            for candidate in deduped
            if candidate.candidate_id in keep_ids
        ]

        tasks = self._finalizer.finalize(set_accepted)
        trace.finalized_task_ids = [task.task_id for task in tasks]

        trace.fidelity_findings.extend(
            self._fidelity_audit.review(
                candidates=set_accepted,
                tasks=tasks,
            )
        )

        trace.reality_validity_findings.extend(
            self._reality_validity_audit.review(
                reality=reality,
                tasks=tasks,
            )
        )

        structurally_invalid_task_ids: set[str] = set()
        for finding in trace.reality_validity_findings:
            if finding.startswith("task:"):
                structurally_invalid_task_ids.add(
                    finding.split(":", 2)[1]
                )

        semantically_valid_tasks = []
        for task in tasks:
            if task.task_id in structurally_invalid_task_ids:
                continue

            review = await self._reasoner.review_final_task_reality(
                reality=reality,
                task=task,
            )
            trace.final_task_reality_reviews.append(review)

            if review.keeps_task:
                semantically_valid_tasks.append(task)

        return TaskGenerationResult(
            discovered_candidates=discovered,
            accepted_candidates=set_accepted,
            tasks=semantically_valid_tasks,
            trace=trace,
        )
