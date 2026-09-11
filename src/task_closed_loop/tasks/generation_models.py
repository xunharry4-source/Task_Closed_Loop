from __future__ import annotations

from dataclasses import dataclass, field

from task_closed_loop.tasks.models import Task, TaskCandidate


@dataclass(frozen=True)
class CandidateReview:
    candidate_id: str
    keep: bool
    challenge: str
    evidence: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class CandidateSetReview:
    keep_candidate_ids: tuple[str, ...]
    challenge: str
    evidence: tuple[str, ...] = ()
    reason: str = ""


@dataclass(frozen=True)
class FinalTaskRealityReview:
    task_id: str
    status: str
    challenge: str
    evidence: tuple[str, ...] = ()
    reason: str = ""

    @property
    def keeps_task(self) -> bool:
        return self.status.lower() == "valid"


@dataclass(frozen=True)
class StructuralFinding:
    code: str
    candidate_id: str
    message: str
    evidence: tuple[str, ...] = ()


@dataclass
class TaskGenerationTrace:
    discovered_candidate_ids: list[str] = field(default_factory=list)
    candidate_reviews: list[CandidateReview] = field(default_factory=list)
    structural_findings: list[StructuralFinding] = field(default_factory=list)
    set_review: CandidateSetReview | None = None
    finalized_task_ids: list[str] = field(default_factory=list)
    fidelity_findings: list[str] = field(default_factory=list)
    reality_validity_findings: list[str] = field(default_factory=list)
    final_task_reality_reviews: list[FinalTaskRealityReview] = field(default_factory=list)


@dataclass
class TaskGenerationResult:
    discovered_candidates: list[TaskCandidate]
    accepted_candidates: list[TaskCandidate]
    tasks: list[Task]
    trace: TaskGenerationTrace

    @property
    def task_count(self) -> int:
        return len(self.tasks)
