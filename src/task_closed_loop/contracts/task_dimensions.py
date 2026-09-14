from __future__ import annotations
from typing import Any, Protocol, Sequence
from .common import TaskAuditResult, TaskDimensionResult, TaskDraftBatch

class TaskDimensionGenerator(Protocol):
    async def generate(
        self,
        *,
        base_batch: TaskDraftBatch,
        audit_result: TaskAuditResult,
        accepted_candidates: Sequence[Any],
        round_number: int,
    ) -> TaskDimensionResult: ...
