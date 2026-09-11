from __future__ import annotations

from .models import DiagnosticSnapshot
from .runner import DiagnosticRunner


def run_all(snapshot: DiagnosticSnapshot):
    return list(DiagnosticRunner().review(snapshot).findings)
