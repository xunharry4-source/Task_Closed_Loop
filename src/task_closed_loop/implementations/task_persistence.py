"""Write finished tasks to the durable store, with their lineage.

This runs after a project's whole pipeline (Stage 3 generate -> Stage 4 audit -> 5/6/7
-> Stage 4) has finished, so only tasks that survived the unchanged audit are written.
The store folds a task that was already proposed (same task_key) into the existing row
instead of inserting a second one, and skips one the user shelved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from task_closed_loop.store.task_store import compute_task_key

MAX_TITLE_CHARS = 120


@dataclass
class TaskPersistenceReport:
    inserted: int = 0
    repeated: int = 0
    shelved: int = 0
    skipped: dict[str, str] = None  # task description -> why

    def __post_init__(self) -> None:
        if self.skipped is None:
            self.skipped = {}


def _title(project_name: str, task) -> str:
    text = " ".join(str(task.description or "").split())
    if len(text) > MAX_TITLE_CHARS:
        text = text[: MAX_TITLE_CHARS - 1].rstrip() + "…"
    prefix = f"【{project_name}】" if project_name else ""
    return f"{prefix}{text}" or prefix or "（无标题任务）"


def _core_target(task) -> list[str]:
    metadata = task.metadata or {}
    anchors = [
        str(value)
        for value in (metadata.get("identity_anchor_refs") or ())
        if str(value).strip()
    ]
    if not anchors:
        anchors = [
            str(value)
            for value in (metadata.get("reality_basis_refs") or ())
            if str(value).strip()
        ]
    relation = " ".join(str(metadata.get("work_relation") or "").lower().split())
    return [relation, *sorted(anchors)]


def save_project_tasks(*, store, project, tasks, logger=None) -> TaskPersistenceReport:
    report = TaskPersistenceReport()
    if store is None:
        return report

    for task in tasks:
        metadata = task.metadata or {}
        source_table = str(metadata.get("source_table") or "").strip()
        source_id = metadata.get("source_id")
        if not source_table or not source_id:
            # Without a real source record the store's trigger would refuse the row,
            # and rightly: the chain requires 问题/价值/需求 -> 任务.
            report.skipped[task.description[:60]] = (
                "缺少来源记录（source_table/source_id），未写入任务库。"
            )
            continue

        task_type = str(metadata.get("task_type") or "").strip()
        task_key = compute_task_key(
            entity_id=project.project_id,
            task_type=task_type,
            core_target=_core_target(task),
        )
        _, outcome = store.save_task(
            entity_id=project.project_id,
            title=_title(project.name, task),
            task_key=task_key,
            task_tier=str(metadata.get("task_tier") or ""),
            task_type=task_type,
            theme=str(metadata.get("theme") or ""),
            theme_kind=str(metadata.get("theme_kind") or ""),
            source_table=source_table,
            source_id=int(source_id),
            evidence=list(metadata.get("reality_basis_refs") or ()),
            expected_result=str(task.expected_reality_result or ""),
            deliverable=str(metadata.get("deliverable") or ""),
            note=str(task.user_value or ""),
            priority=int(metadata.get("priority") or 3),
            task_origin=f"{metadata.get('source_kind', '')}:{source_id}",
        )
        setattr(report, outcome, getattr(report, outcome) + 1)

    if logger is not None:
        logger.info(
            "task_store.saved project=%s inserted=%d repeated=%d shelved=%d skipped=%d",
            project.project_id,
            report.inserted,
            report.repeated,
            report.shelved,
            len(report.skipped),
        )
    return report
