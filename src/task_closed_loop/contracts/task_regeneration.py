from __future__ import annotations
from typing import Any, Protocol, Sequence
from .common import TaskDraftBatch

class TaskRegenerator(Protocol):
    async def regenerate(
        self,
        *,
        base_batch: TaskDraftBatch,
        current_tasks: Sequence[Any],
        accepted_candidates: Sequence[Any],
        dimensions: Sequence[Any],
        round_number: int,
    ) -> TaskDraftBatch: ...
