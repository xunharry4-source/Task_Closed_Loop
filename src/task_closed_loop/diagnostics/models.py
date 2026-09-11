from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from task_closed_loop.execution.models import ExecutionContext
from task_closed_loop.information_flow.models import InformationFlowContext
from task_closed_loop.integration.models import CapabilityDescriptor
from task_closed_loop.reality.models import RealityBuildInput, RealitySnapshot
from task_closed_loop.tasks.models import Task, TaskCandidate


@dataclass(frozen=True)
class DiagnosticFinding:
    root: str
    code: str
    severity: str
    subject: str
    challenge: str
    evidence: tuple[str, ...] = ()
    consequence: str = ""


@dataclass(frozen=True)
class TaskReviewClaim:
    task_identity: str
    reality_id: str
    basis_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlannedActionReview:
    action_id: str
    execution_intent_id: str
    target_ref: str
    scope_keys: tuple[str, ...]
    required_capability_ids: tuple[str, ...] = ()
    execution_context: ExecutionContext | None = None
    approval_required: bool = False


@dataclass(frozen=True)
class InformationFlowReview:
    flow_id: str
    context: InformationFlowContext
    permitted_destination_refs: tuple[str, ...] = ()
    permitted_audience: tuple[str, ...] = ()
    source_lineage_complete: bool = True


@dataclass(frozen=True)
class DiagnosticSnapshot:
    reality_input: RealityBuildInput
    reality: RealitySnapshot
    existing_tasks: tuple[Task, ...] = ()
    effective_existing_tasks: tuple[Task, ...] = ()
    candidate_tasks: tuple[TaskCandidate, ...] = ()
    capabilities: tuple[CapabilityDescriptor, ...] = ()
    planned_actions: tuple[PlannedActionReview, ...] = ()
    information_flows: tuple[InformationFlowReview, ...] = ()


@dataclass(frozen=True)
class DiagnosticReport:
    findings: tuple[DiagnosticFinding, ...]

    @property
    def passed(self) -> bool:
        return not self.findings

    def for_root(self, root: str) -> tuple[DiagnosticFinding, ...]:
        return tuple(f for f in self.findings if f.root == root)

    def summary(self) -> dict[str, int]:
        roots = ("R1", "R2", "R3", "R4", "R5")
        return {root: len(self.for_root(root)) for root in roots}


def ref_id(value: Any) -> str | None:
    if isinstance(value, str):
        return value

    for attr in (
        "resource_id",
        "evidence_id",
        "effect_id",
        "task_id",
        "task_identity",
        "history_id",
        "id",
    ):
        candidate = getattr(value, attr, None)
        if candidate:
            return str(candidate)

    if isinstance(value, dict):
        for key in (
            "resource_id",
            "evidence_id",
            "effect_id",
            "task_id",
            "task_identity",
            "history_id",
            "id",
            "ref",
        ):
            if value.get(key):
                return str(value[key])

    return None


def collect_refs(values: Iterable[Any]) -> set[str]:
    out: set[str] = set()
    for value in values:
        rid = ref_id(value)
        if rid:
            out.add(rid)
    return out


def current_reality_refs(snapshot: DiagnosticSnapshot) -> set[str]:
    return (
        collect_refs(snapshot.reality_input.resources)
        | collect_refs(snapshot.reality_input.evidence)
        | collect_refs(snapshot.reality_input.external_effects)
        | collect_refs(snapshot.reality_input.execution_deltas)
    )


def history_refs(snapshot: DiagnosticSnapshot) -> set[str]:
    return collect_refs(snapshot.reality_input.related_history)


def evidence_map(snapshot: DiagnosticSnapshot) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for evidence in snapshot.reality_input.evidence:
        out.setdefault(evidence.evidence_id, []).append(evidence)
    return out



def candidate_basis_refs(candidate: Any) -> tuple[str, ...]:
    formal = getattr(candidate, "reality_basis_refs", ())
    if formal:
        return tuple(str(x) for x in formal)

    metadata = getattr(candidate, "metadata", {}) or {}
    legacy = metadata.get("basis_refs", ())
    return tuple(str(x) for x in legacy)

def normalize_scope(scope: Any) -> set[str]:
    if scope is None:
        return set()

    if isinstance(scope, dict):
        out: set[str] = set()
        for key, value in scope.items():
            if isinstance(value, (str, int, float, bool)):
                out.add(f"{key}={value}")
            else:
                out.add(str(key))
        return out

    if isinstance(scope, (list, tuple, set, frozenset)):
        return {str(item) for item in scope}

    return {str(scope)}


def target_ref(target: Any) -> str:
    if isinstance(target, str):
        return target
    if isinstance(target, dict):
        for key in ("resource_id", "reality_id", "target_id", "id", "ref"):
            if target.get(key):
                return str(target[key])
        return repr(sorted(target.items()))
    return str(target)
