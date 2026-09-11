from __future__ import annotations

from task_closed_loop.reality.models import RealitySnapshot
from task_closed_loop.tasks.generation_audit import current_reality_refs
from task_closed_loop.tasks.models import Task


class TaskRealityValidityAudit:
    def review(
        self,
        reality: RealitySnapshot,
        tasks: list[Task],
    ) -> list[str]:
        findings: list[str] = []
        available_refs = current_reality_refs(reality)

        for task in tasks:
            if task.reality_id != reality.reality_id:
                findings.append(
                    f"task:{task.task_id}:reality_identity_mismatch"
                )

            basis_refs = set(
                str(x)
                for x in task.metadata.get(
                    "reality_basis_refs",
                    (),
                )
            )
            missing = basis_refs - available_refs
            if missing:
                findings.append(
                    f"task:{task.task_id}:missing_reality_basis:"
                    + ",".join(sorted(missing))
                )

        return findings
