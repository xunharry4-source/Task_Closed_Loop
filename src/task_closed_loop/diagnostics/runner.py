from __future__ import annotations

from .models import DiagnosticReport, DiagnosticSnapshot
from .r1_context_scope import R1Reviewer
from .r2_evidence_continuity import R2Reviewer
from .r3_effect_continuity import R3Reviewer
from .r4_execution_context import R4Reviewer
from .r5_information_flow import R5Reviewer


DEFAULT_REVIEWERS = (
    R1Reviewer(),
    R2Reviewer(),
    R3Reviewer(),
    R4Reviewer(),
    R5Reviewer(),
)


class DiagnosticRunner:
    """
    Five reviewers inspect the same snapshot independently.
    Findings are aggregated only after all reviews finish.
    """

    def __init__(self, reviewers=DEFAULT_REVIEWERS):
        self._reviewers = tuple(reviewers)

    def review(self, snapshot: DiagnosticSnapshot) -> DiagnosticReport:
        findings = []
        for reviewer in self._reviewers:
            findings.extend(reviewer.review(snapshot))
        return DiagnosticReport(findings=tuple(findings))
