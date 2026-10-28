from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from task_closed_loop.tasks.models import (
    Task,
    TaskCandidate,
)


@dataclass(frozen=True)
class DiscoverySignal:
    """A reality-grounded need/opportunity/problem worth considering before Task formation.

    Discovery is deliberately broader than Task. A signal may be valuable even when the
    current Capability set cannot act on it yet. `discovery_kind` is free text rather
    than an enum so the model is not forced into a pre-built taxonomy.
    """

    discovery_id: str
    discovery_kind: str
    reality_relation: str
    user_relevance_hypothesis: str
    desired_change_or_answer: str
    independence_reason: str
    reality_basis_refs: tuple[str, ...] = ()
    relevant_capability_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskOutcomeRecord:
    """Evidence-bearing lifecycle result that is allowed to trigger Task descendants.

    Task proliferation must be driven by an observed outcome, failure, block, or other
    verified lifecycle transition. A Task's text alone is never a proliferation trigger.
    """

    outcome_id: str
    task_id: str
    outcome_status: str
    result_summary: str
    evidence_refs: tuple[str, ...] = ()
    effect_refs: tuple[str, ...] = ()
    payload: Any = None
    # Optional compact, evidence-bearing view used specifically for Task discovery.
    # Raw payload may be much larger and remains available to the execution layer.
    discovery_payload: Any = None
    supersedes_outcome_ids: tuple[str, ...] = ()
    # Stable identities of concrete reality objects exposed by this Outcome.
    # Examples: gmail:message:<id>, drive:file:<id>, db:row:<id>.  These are
    # optional because not every aggregate/unknown result has a safe stable subject.
    subject_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskSeed:
    seed_id: str
    work_relation: str
    result_goal: str
    user_value_hypothesis: str
    independence_reason: str
    reality_basis_refs: tuple[str, ...] = ()
    required_capability_ids: tuple[str, ...] = ()
    # Stable business-object identity used for deduplication across changing
    # Observation Outcome IDs. For proliferation it may only come from verified
    # parent Outcome subject_refs (or other already-materialized stable reality refs).
    identity_anchor_refs: tuple[str, ...] = ()
    origin_type: str = "reality_discovery"
    source_discovery_ids: tuple[str, ...] = ()
    parent_task_ids: tuple[str, ...] = ()
    parent_outcome_ids: tuple[str, ...] = ()
    proliferation_reason: str = ""


@dataclass(frozen=True)
class CandidateFieldRepair:
    description: str
    expected_reality_result: str
    user_value: str
    execution_steps: tuple[str, ...]


@dataclass(frozen=True)
class CandidateFailureContext:
    candidate_id: str
    task_identity: str
    work_relation: str
    expected_reality_result: str
    stage: str
    reason: str
    field_issues: tuple[str, ...] = ()
    structural_findings: tuple[str, ...] = ()


@dataclass(frozen=True)
class CoverageDimension:
    dimension_id: str
    focus: str
    user_question: str
    value_reason: str
    independence_reason: str
    reality_basis_refs: tuple[str, ...] = ()
    relevant_capability_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateReview:
    candidate_id: str
    keep: bool
    challenge: str
    evidence: tuple[str, ...] = ()
    reason: str = ""
    repair_required: bool = False
    field_issues: tuple[str, ...] = ()

    @property
    def core_valid(self) -> bool:
        """`keep` means the underlying Task relation is valid."""
        return self.keep


@dataclass(frozen=True)
class CandidateFieldReview:
    """Sixth-step field-quality review; only runs after core validity passes."""

    candidate_id: str
    repair_required: bool
    field_issues: tuple[str, ...] = ()
    challenge: str = ""
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
    discovery_signals: list[DiscoverySignal] = field(
        default_factory=list
    )
    rejected_discovery_ids: list[str] = field(
        default_factory=list
    )
    # Why each discovery was dropped. Without this a rejected discovery is
    # indistinguishable from "the model found nothing".
    rejected_discovery_reasons: dict[str, str] = field(
        default_factory=dict
    )
    discovery_error: str = ""
    discovery_seeds: list[TaskSeed] = field(
        default_factory=list
    )
    observation_acquisition_attempted: bool = False
    observation_acquisition_ids: list[str] = field(
        default_factory=list
    )
    observation_acquisition_candidate_ids: list[str] = field(
        default_factory=list
    )
    observation_acquisition_suppressed: dict[str, str] = field(
        default_factory=dict
    )
    proliferation_attempted: bool = False
    proliferation_succeeded: bool = False
    proliferation_error: str = ""
    proliferation_outcomes: list[TaskOutcomeRecord] = field(
        default_factory=list
    )
    # Outcome Receipt state for at-least-once event delivery. Canonical Outcomes are
    # marked consumed only after the proliferation phase completed successfully, even
    # when that phase legitimately produced zero descendants. The caller can persist
    # these IDs and feed them back on the next cycle.
    consumed_outcome_ids: list[str] = field(default_factory=list)
    replayed_outcome_ids: list[str] = field(default_factory=list)
    proliferation_rejected_outcomes: dict[str, str] = field(
        default_factory=dict
    )
    proliferation_payload_context: dict[str, dict[str, Any]] = field(
        default_factory=dict
    )
    # Outcomes that reached the model but yielded no descendant. The architecture
    # allows a genuine zero, so this is not an error — but without recording it,
    # "nothing worth doing" is indistinguishable from an unstable empty answer.
    proliferation_zero_seed_outcome_ids: list[str] = field(
        default_factory=list
    )
    proliferation_seeds: list[TaskSeed] = field(
        default_factory=list
    )
    coverage_expansion_seeds: list[TaskSeed] = field(
        default_factory=list
    )
    seed_validation_errors: dict[
        str,
        str,
    ] = field(
        default_factory=dict
    )
    seed_materialization_errors: dict[
        str,
        str,
    ] = field(
        default_factory=dict
    )
    repaired_candidate_ids: list[str] = field(
        default_factory=list
    )
    unresolved_field_issues: dict[
        str,
        list[str],
    ] = field(
        default_factory=dict
    )
    rejected_candidate_contexts: list[
        CandidateFailureContext
    ] = field(
        default_factory=list
    )
    coverage_expansion_attempted: bool = False
    coverage_expansion_succeeded: bool = False
    coverage_expansion_error: str = ""
    coverage_expansion_dimensions: list[
        CoverageDimension
    ] = field(
        default_factory=list
    )
    coverage_expansion_second_pass_candidate_ids: list[
        str
    ] = field(
        default_factory=list
    )
    coverage_expansion_preserved_first_pass_ids: list[
        str
    ] = field(
        default_factory=list
    )
    discovered_candidate_ids: list[str] = field(
        default_factory=list
    )
    candidate_reviews: list[
        CandidateReview
    ] = field(
        default_factory=list
    )
    structural_findings: list[
        StructuralFinding
    ] = field(
        default_factory=list
    )
    set_review: CandidateSetReview | None = None
    finalized_task_ids: list[str] = field(
        default_factory=list
    )
    fidelity_findings: list[str] = field(
        default_factory=list
    )
    reality_validity_findings: list[str] = field(
        default_factory=list
    )
    final_task_reality_reviews: list[
        FinalTaskRealityReview
    ] = field(
        default_factory=list
    )


@dataclass
class TaskGenerationResult:
    discovered_candidates: list[
        TaskCandidate
    ]
    accepted_candidates: list[
        TaskCandidate
    ]
    tasks: list[Task]
    trace: TaskGenerationTrace

    @property
    def task_count(self) -> int:
        return len(self.tasks)

    @property
    def discoveries(self) -> list[DiscoverySignal]:
        return list(self.trace.discovery_signals)

    @property
    def observation_tasks(self) -> list[Task]:
        return [
            task
            for task in self.tasks
            if str(task.metadata.get("origin_type", ""))
            == "observation_acquisition"
        ]
