from __future__ import annotations
from pathlib import Path
from typing import Protocol
from .common import ResourceCapabilityResult

class ResourceCapabilityAnalyzer(Protocol):
    def analyze(self, cli_project: Path) -> ResourceCapabilityResult: ...
