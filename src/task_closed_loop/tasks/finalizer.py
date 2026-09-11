from __future__ import annotations

from task_closed_loop.tasks.models import Task, TaskCandidate


class DeterministicTaskFinalizer:
    """
    Finalizer performs a deterministic field-preserving conversion.
    It does not ask the LLM to rewrite an audited candidate.
    """

    def finalize(self, candidates: list[TaskCandidate]) -> list[Task]:
        return [candidate.materialize() for candidate in candidates]


class FinalizerFidelityAudit:
    def review(
        self,
        candidates: list[TaskCandidate],
        tasks: list[Task],
    ) -> list[str]:
        findings: list[str] = []

        candidate_by_id = {
            candidate.candidate_id: candidate
            for candidate in candidates
        }

        for task in tasks:
            candidate_id = str(task.metadata.get("candidate_id", ""))
            candidate = candidate_by_id.get(candidate_id)

            if candidate is None:
                findings.append(
                    f"task:{task.task_id}:missing_candidate_origin"
                )
                continue

            expected = (
                candidate.task_identity,
                candidate.reality_id,
                candidate.description,
                candidate.reality_basis,
                candidate.expected_reality_result,
            )
            actual = (
                task.task_identity,
                task.reality_id,
                task.description,
                task.reality_basis,
                task.expected_reality_result,
            )

            if actual != expected:
                findings.append(
                    f"task:{task.task_id}:finalizer_fidelity_mismatch"
                )

        if len(tasks) != len(candidates):
            findings.append("finalizer_count_mismatch")

        return findings
