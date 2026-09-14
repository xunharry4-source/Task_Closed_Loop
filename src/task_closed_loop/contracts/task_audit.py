from __future__ import annotations
from typing import Protocol
from .common import TaskAuditResult, TaskDraftBatch

class TaskAuditor(Protocol):
    async def audit(self, batch: TaskDraftBatch) -> TaskAuditResult: ...
