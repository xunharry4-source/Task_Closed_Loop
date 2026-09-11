from __future__ import annotations

from typing import Protocol

from .models import DiagnosticFinding, DiagnosticSnapshot


class DestructiveReviewer(Protocol):
    root: str

    def review(self, snapshot: DiagnosticSnapshot) -> list[DiagnosticFinding]:
        ...
