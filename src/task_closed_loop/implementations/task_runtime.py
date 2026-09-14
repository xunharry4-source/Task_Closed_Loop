from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from task_closed_loop.app.orchestrator import RuntimeOrchestrator
from task_closed_loop.llm import build_llm
from task_closed_loop.reality.builder import RealityEngine
from task_closed_loop.tasks.continuity import TaskContinuityEngine
from task_closed_loop.tasks.generator import TaskGenerationEngine


@dataclass(frozen=True)
class TaskRuntimeComponents:
    task_llm: object
    audit_llm: object
    orchestrator: RuntimeOrchestrator


class LazyTaskRuntimeProvider:
    """Creates Task/Audit LLMs only when Stage 3 actually begins."""

    def __init__(self, *, config: dict, project_root: Path, minimum_tasks: int):
        self.config = config
        self.project_root = Path(project_root).resolve()
        self.minimum_tasks = int(minimum_tasks)
        self._components: TaskRuntimeComponents | None = None
        self._task_validated = False
        self._audit_validated = False

    def _build(self) -> TaskRuntimeComponents:
        if self._components is not None:
            return self._components
        task_llm = build_llm(self.config, self.project_root, profile="task")
        audit_llm = build_llm(self.config, self.project_root, profile="audit")
        task_generation_cfg = self.config.get("task_generation", {})
        need_cfg = task_generation_cfg.get("need_opportunity_discovery", {})
        proliferation_cfg = task_generation_cfg.get("task_proliferation", {})
        orchestrator = RuntimeOrchestrator(
            reality_engine=RealityEngine(task_llm),
            task_continuity=TaskContinuityEngine(task_llm),
            task_generation=TaskGenerationEngine(
                task_reasoner=task_llm,
                audit_reasoner=audit_llm,
                # Stage 6 is the only formal dimension-expansion location.
                coverage_expansion_min_tasks=0,
                enable_need_discovery=bool(need_cfg.get("enabled", True)),
                enable_task_proliferation=bool(proliferation_cfg.get("enabled", True)),
                max_inline_outcome_payload_bytes=int(
                    proliferation_cfg.get("max_inline_outcome_payload_bytes", 65536)
                ),
                max_total_outcome_payload_bytes=int(
                    proliferation_cfg.get("max_total_outcome_payload_bytes", 262144)
                ),
            ),
        )
        self._components = TaskRuntimeComponents(task_llm, audit_llm, orchestrator)
        return self._components

    async def components(self) -> TaskRuntimeComponents:
        return self._build()

    async def validate_task(self) -> TaskRuntimeComponents:
        components = self._build()
        if not self._task_validated:
            validate = getattr(components.task_llm, "validate_connection", None)
            if validate is not None:
                await validate()
            self._task_validated = True
        return components

    async def validate_audit(self) -> TaskRuntimeComponents:
        components = self._build()
        if not self._audit_validated:
            validate = getattr(components.audit_llm, "validate_connection", None)
            if validate is not None:
                await validate()
            self._audit_validated = True
        return components
