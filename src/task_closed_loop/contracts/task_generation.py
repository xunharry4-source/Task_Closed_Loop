from __future__ import annotations
from typing import Any, Protocol, Sequence
from .common import TaskDraftBatch

class InitialTaskGenerator(Protocol):
    async def generate(self, resources: Sequence[Any], capabilities: Sequence[Any]) -> TaskDraftBatch: ...
