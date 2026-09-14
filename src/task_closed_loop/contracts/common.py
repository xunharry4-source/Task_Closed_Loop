from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CliProjectResult:
    root: Path
    created: bool
    repaired_by_cli: bool
    repair_engine: str | None = None

    @property
    def repaired_from_template(self) -> bool:
        # Compatibility only: V1.2 never template-repairs an existing invalid project.
        return False


@dataclass(frozen=True)
class ResourceCapabilityResult:
    cli_root: Path
    resources_path: Path
    capabilities_path: Path
    resource_analysis_path: Path
    function_analysis_path: Path
    resources: tuple[Any, ...]
    capabilities: tuple[Any, ...]
    local_resource_count: int
    remote_resource_count: int
    function_count: int
    cli_engine: str


@dataclass(frozen=True)
class TaskDraftBatch:
    prepared: Any
    draft: Any
    existing_tasks: tuple[Any, ...]
    all_existing_tasks: tuple[Any, ...]
    round_number: int = 0
    source_stage: int = 3


@dataclass(frozen=True)
class TaskAuditResult:
    generation: Any
    tasks: tuple[Any, ...]
    accepted_candidates: tuple[Any, ...]
    rejected_count: int
    round_number: int = 0


@dataclass(frozen=True)
class TaskCountDecision:
    qualified_tasks: tuple[Any, ...]
    threshold: int
    too_few: bool


@dataclass(frozen=True)
class TaskDimensionResult:
    dimensions: tuple[Any, ...]
    round_number: int


@dataclass
class PipelineCycleView:
    reality: Any
    effective_existing_tasks: list[Any]
    task_generation: Any

    @property
    def new_tasks(self):
        return self.task_generation.tasks

    @property
    def new_task_candidates(self):
        return self.task_generation.accepted_candidates

    @property
    def discoveries(self):
        return self.task_generation.discoveries

    @property
    def observation_tasks(self):
        return self.task_generation.observation_tasks

    @property
    def consumed_outcome_ids(self):
        return list(self.task_generation.trace.consumed_outcome_ids)


@dataclass(frozen=True)
class StageRecord:
    stage: int
    name: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProductionPipelineResult:
    reality: Any
    tasks: list[Any]
    rounds: int
    stages: list[StageRecord] = field(default_factory=list)
    dimensions: list[Any] = field(default_factory=list)
    last_cycle: Any | None = None
    cli_project: Path | None = None
    resources_path: Path | None = None
    capabilities_path: Path | None = None

    @property
    def stage_order(self) -> list[int]:
        return [record.stage for record in self.stages]

    def to_payload(self) -> dict[str, Any]:
        return {
            "rounds": self.rounds,
            "stage_order": self.stage_order,
            "task_count": len(self.tasks),
            "stages": [
                {"stage": record.stage, "name": record.name, **record.detail}
                for record in self.stages
            ],
            "cli_project": str(self.cli_project) if self.cli_project else None,
            "resources_path": str(self.resources_path) if self.resources_path else None,
            "capabilities_path": str(self.capabilities_path) if self.capabilities_path else None,
        }
