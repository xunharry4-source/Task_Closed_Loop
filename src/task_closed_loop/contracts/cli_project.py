from __future__ import annotations
from typing import Protocol
from .common import CliProjectResult

class CliProjectManager(Protocol):
    def ensure_project(self) -> CliProjectResult: ...
