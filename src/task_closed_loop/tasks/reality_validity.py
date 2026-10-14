from __future__ import annotations

from task_closed_loop.integration.models import (
    CapabilityDescriptor,
    ResourceSnapshot,
)
from task_closed_loop.reality.models import RealitySnapshot
from task_closed_loop.tasks.generation_audit import reference_context
from task_closed_loop.tasks.models import Task
from task_closed_loop.tasks.references import format_problems


class TaskRealityValidityAudit:
    def review(
        self,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        tasks: list[Task],
        capabilities: list[CapabilityDescriptor] | None = None,
    ) -> list[str]:
        findings: list[str] = []
        # Same grammar and same resolver as the candidate audit: a citation the
        # candidate audit accepted must not be dropped here by a stricter rule.
        references = reference_context(
            reality,
            resources,
            capabilities or [],
            allow_capability=True,
        )

        for task in tasks:
            if task.reality_id != reality.reality_id:
                findings.append(
                    f"task:{task.task_id}:reality_identity_mismatch"
                )

            basis_refs = {
                str(x).strip()
                for x in task.metadata.get(
                    "reality_basis_refs",
                    (),
                )
            }
            missing = references.problems(basis_refs)
            if missing:
                findings.append(
                    f"task:{task.task_id}:missing_reality_basis:"
                    + format_problems(missing)
                )

        return findings
