from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from task_closed_loop.tasks.generation_models import TaskOutcomeRecord
from task_closed_loop.tasks.models import Task

from .contracts import CapabilityBuildRequest, CapabilityRequest, CapabilityResult
from .host import CapabilityProjectHost


@dataclass(frozen=True)
class IntegratedExecutionResult:
    capability_result: CapabilityResult
    task_outcome: TaskOutcomeRecord
    capability_built: bool = False


class TaskCapabilityCoordinator:
    """Bridge from an accepted Task to the persistent capability workspace.

    Task generation/audit remains authoritative in task_closed_loop.tasks. This class
    only handles execution after a Task has already survived those gates.
    """

    def __init__(self, host: CapabilityProjectHost):
        self.host = host

    def ensure_capability(self, build_request: CapabilityBuildRequest, *, explicit_engine: Optional[str] = None) -> bool:
        existing = self.host.registry.find(build_request.capability_id)
        if existing and existing.get("status") in {"verified", "enabled"}:
            return False
        self.host.create_build(build_request)
        self.host.run_cli_build(build_request.build_id, explicit_engine=explicit_engine)
        test_result = self.host.test_build(build_request.build_id)
        if not test_result.passed:
            raise RuntimeError(f"capability build tests failed: {build_request.capability_id}")
        self.host.promote_build(build_request.build_id)
        return True

    def execute_task(
        self,
        task: Task,
        request: CapabilityRequest,
        *,
        build_request: CapabilityBuildRequest | None = None,
        explicit_engine: Optional[str] = None,
    ) -> IntegratedExecutionResult:
        built = False
        if build_request is not None:
            if build_request.requested_by_task_id and build_request.requested_by_task_id != task.task_id:
                raise ValueError("CapabilityBuildRequest.requested_by_task_id does not match Task")
            built = self.ensure_capability(build_request, explicit_engine=explicit_engine)
        result = self.host.execute(request)
        status = "succeeded" if result.trusted else (
            "failed" if result.verification_status == "failed" else "unverified"
        )
        summary = (
            f"Capability {request.capability_id} completed with process_status={result.process_status}, "
            f"verification_status={result.verification_status}."
        )
        evidence_refs = tuple(
            str(item.get("ref") or item.get("id") or item)
            for item in result.evidence
        )
        outcome = TaskOutcomeRecord(
            outcome_id=f"capability:{request.request_id}",
            task_id=task.task_id,
            outcome_status=status,
            result_summary=summary,
            evidence_refs=evidence_refs,
            payload=result.to_dict(),
            discovery_payload={
                "capability_id": request.capability_id,
                "verification_status": result.verification_status,
                "trusted": result.trusted,
                "outputs": result.outputs,
                "verification": result.verification,
            },
        )
        return IntegratedExecutionResult(result, outcome, built)
