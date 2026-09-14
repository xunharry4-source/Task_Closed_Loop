from __future__ import annotations
from typing import Any, Protocol, Sequence
from .common import TaskCountDecision

class TaskCountPolicy(Protocol):
    def evaluate(self, tasks: Sequence[Any]) -> TaskCountDecision: ...
