from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from task_closed_loop.tasks.generation_models import TaskOutcomeRecord
from task_closed_loop.tasks.models import Task


@dataclass(frozen=True)
class OutcomeNormalizationResult:
    """Canonical outcome view shared by observation, resources and proliferation."""

    usable: tuple[TaskOutcomeRecord, ...]
    rejected: dict[str, str]


def _task_index(all_existing_tasks: Iterable[Task]):
    task_by_id: dict[str, Task] = {}
    ambiguous_task_ids: set[str] = set()
    for task in all_existing_tasks:
        task_id = str(task.task_id).strip()
        if not task_id:
            continue
        previous = task_by_id.get(task_id)
        if previous is None:
            task_by_id[task_id] = task
        elif previous != task:
            ambiguous_task_ids.add(task_id)
    for task_id in ambiguous_task_ids:
        task_by_id.pop(task_id, None)
    return task_by_id, ambiguous_task_ids


def normalize_task_outcomes(
    task_outcomes: Iterable[TaskOutcomeRecord],
    all_existing_tasks: Iterable[Task],
) -> OutcomeNormalizationResult:
    """Validate and canonicalize lifecycle events before any Task-layer consumer.

    Rules:
    - parent task lineage must be uniquely resolvable;
    - required event fields must exist;
    - identical duplicate outcome IDs collapse idempotently;
    - conflicting reuse of an outcome ID is rejected;
    - supersession may only target the same parent when the target is present;
    - supersession cycles are invalid rather than silently erasing all reality;
    - superseded outcomes are inactive and excluded from downstream consumers.

    Unknown superseded IDs are allowed because a newer event can legitimately refer
    to an older event that is not included in the current cycle input.
    """

    task_by_id, ambiguous_task_ids = _task_index(all_existing_tasks)
    rejected: dict[str, str] = {}
    outcome_by_id: dict[str, TaskOutcomeRecord] = {}
    conflicting_outcome_ids: set[str] = set()

    for outcome in task_outcomes:
        # Set-like reference fields are canonicalized before duplicate identity checks.
        # Reordered evidence/subject/supersession refs must not turn the same event into
        # a false conflicting Outcome.
        outcome = replace(
            outcome,
            evidence_refs=tuple(sorted({
                str(value).strip() for value in outcome.evidence_refs if str(value).strip()
            })),
            effect_refs=tuple(sorted({
                str(value).strip() for value in outcome.effect_refs if str(value).strip()
            })),
            supersedes_outcome_ids=tuple(sorted({
                str(value).strip()
                for value in outcome.supersedes_outcome_ids
                if str(value).strip()
            })),
            subject_refs=tuple(sorted({
                str(value).strip() for value in outcome.subject_refs if str(value).strip()
            })),
        )
        outcome_id = str(outcome.outcome_id).strip()
        task_id = str(outcome.task_id).strip()
        status = str(outcome.outcome_status).strip()
        summary = str(outcome.result_summary).strip()

        reason = ""
        if not outcome_id:
            reason = "TaskOutcomeRecord 缺少 outcome_id。"
        elif not task_id:
            reason = "TaskOutcomeRecord 缺少 task_id。"
        elif task_id in ambiguous_task_ids:
            reason = (
                "TaskOutcomeRecord 引用了重复且互相冲突的 task_id；"
                "parent lineage 无法唯一确定。"
            )
        elif task_id not in task_by_id:
            reason = "TaskOutcomeRecord 引用了当前不存在的 parent task_id。"
        elif not status:
            reason = "TaskOutcomeRecord 缺少 outcome_status。"
        elif not summary:
            reason = "TaskOutcomeRecord 缺少 result_summary。"

        if reason:
            if outcome_id:
                rejected[outcome_id] = reason
            continue

        previous = outcome_by_id.get(outcome_id)
        if previous is None:
            outcome_by_id[outcome_id] = outcome
        elif previous != outcome:
            conflicting_outcome_ids.add(outcome_id)

    for outcome_id in sorted(conflicting_outcome_ids):
        outcome_by_id.pop(outcome_id, None)
        rejected[outcome_id] = (
            "conflicting TaskOutcomeRecord values reuse the same outcome_id"
        )

    # Validate direct supersession relations before graph processing.
    invalid_superseders: set[str] = set()
    for outcome_id, outcome in list(outcome_by_id.items()):
        supersedes = tuple(
            str(value).strip()
            for value in outcome.supersedes_outcome_ids
            if str(value).strip()
        )
        if outcome_id in supersedes:
            rejected[outcome_id] = "TaskOutcomeRecord 不能 supersede 自己。"
            invalid_superseders.add(outcome_id)
            continue

        for superseded_id in supersedes:
            older = outcome_by_id.get(superseded_id)
            if older is None:
                continue
            if str(older.task_id).strip() != str(outcome.task_id).strip():
                rejected[outcome_id] = (
                    "TaskOutcomeRecord 只能 supersede 同一 parent Task 的 Outcome。"
                )
                invalid_superseders.add(outcome_id)
                break

    for outcome_id in invalid_superseders:
        outcome_by_id.pop(outcome_id, None)

    # Detect cycles among currently known valid outcomes. A cycle has no coherent
    # "newer than" direction, so every event in the cycle is rejected.
    edges: dict[str, tuple[str, ...]] = {}
    for outcome_id, outcome in outcome_by_id.items():
        edges[outcome_id] = tuple(
            target
            for target in (
                str(value).strip()
                for value in outcome.supersedes_outcome_ids
                if str(value).strip()
            )
            if target in outcome_by_id
        )

    state: dict[str, int] = {}
    stack: list[str] = []
    stack_index: dict[str, int] = {}
    cycle_nodes: set[str] = set()

    def visit(node: str) -> None:
        current = state.get(node, 0)
        if current == 2:
            return
        if current == 1:
            start = stack_index.get(node, 0)
            cycle_nodes.update(stack[start:])
            return

        state[node] = 1
        stack_index[node] = len(stack)
        stack.append(node)
        for target in edges.get(node, ()):
            visit(target)
        stack.pop()
        stack_index.pop(node, None)
        state[node] = 2

    for outcome_id in tuple(outcome_by_id):
        if state.get(outcome_id, 0) == 0:
            visit(outcome_id)

    for outcome_id in sorted(cycle_nodes):
        outcome_by_id.pop(outcome_id, None)
        rejected[outcome_id] = (
            "Outcome supersession cycle detected；循环替代关系无法确定当前有效现实。"
        )

    # Only valid non-cyclic superseders are allowed to retire older outcomes.
    superseded_outcome_ids: set[str] = set()
    for outcome in outcome_by_id.values():
        for value in outcome.supersedes_outcome_ids:
            superseded_id = str(value).strip()
            if superseded_id and superseded_id in outcome_by_id:
                superseded_outcome_ids.add(superseded_id)

    for superseded_id in sorted(superseded_outcome_ids):
        outcome_by_id.pop(superseded_id, None)
        rejected[superseded_id] = (
            "Outcome 已被同一 parent Task 的更新 Outcome 显式 supersede。"
        )

    return OutcomeNormalizationResult(
        usable=tuple(outcome_by_id.values()),
        rejected=rejected,
    )
