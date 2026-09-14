from __future__ import annotations
from pathlib import Path

from task_closed_loop.implementations.artifacts import YamlProductionArtifactWriter
from task_closed_loop.implementations.cli_project import DefaultCliProjectManager, cli_project_root
from task_closed_loop.implementations.resource_analysis import CliResourceCapabilityAnalyzer
from task_closed_loop.implementations.task_audit import LlmTaskAuditor
from task_closed_loop.implementations.task_count import QualifiedBusinessTaskCountPolicy
from task_closed_loop.implementations.task_dimensions import LlmTaskDimensionGenerator
from task_closed_loop.implementations.task_generation import LlmInitialTaskGenerator
from task_closed_loop.implementations.task_regeneration import LlmTaskRegenerator
from task_closed_loop.implementations.task_runtime import LazyTaskRuntimeProvider
from task_closed_loop.pipeline import LockedProductionPipeline


def build_locked_production_pipeline(*, config: dict, project_root: Path, minimum_tasks: int, max_rounds: int, logger=None):
    root = Path(project_root).resolve()
    cli_root = cli_project_root(config, root).resolve()
    provider = LazyTaskRuntimeProvider(config=config, project_root=root, minimum_tasks=minimum_tasks)
    return LockedProductionPipeline(
        cli_project=DefaultCliProjectManager(config=config, project_root=root, logger=logger),
        resource_analysis=CliResourceCapabilityAnalyzer(config=config, project_root=root, logger=logger),
        task_generation=LlmInitialTaskGenerator(runtime_provider=provider),
        task_audit=LlmTaskAuditor(runtime_provider=provider),
        task_count=QualifiedBusinessTaskCountPolicy(minimum=minimum_tasks),
        task_dimensions=LlmTaskDimensionGenerator(runtime_provider=provider),
        task_regeneration=LlmTaskRegenerator(runtime_provider=provider),
        artifacts=YamlProductionArtifactWriter(cli_root / "generated"),
        max_rounds=max_rounds,
    )
