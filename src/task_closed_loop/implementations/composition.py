from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from task_closed_loop.implementations.artifacts import YamlProductionArtifactWriter
from task_closed_loop.implementations.cli_project import DefaultCliProjectManager, cli_project_root
from task_closed_loop.implementations.resource_analysis import CliResourceCapabilityAnalyzer
from task_closed_loop.implementations.task_audit import LlmTaskAuditor
from task_closed_loop.implementations.task_count import QualifiedBusinessTaskCountPolicy
from task_closed_loop.implementations.task_dimensions import LlmTaskDimensionGenerator
from task_closed_loop.implementations.task_generation import LlmInitialTaskGenerator
from task_closed_loop.implementations.task_regeneration import LlmTaskRegenerator
from task_closed_loop.implementations.resource_analysis.project_scoped import (
    CachedProjectScopedAnalyzer,
    ProjectStage2Cache,
)
from task_closed_loop.implementations.task_generation.skill_chain import (
    ProjectChainTaskGenerator,
    ProjectChainTaskRegenerator,
)
from task_closed_loop.implementations.task_runtime import LazyTaskRuntimeProvider
from task_closed_loop.pipeline import LockedProductionPipeline
from task_closed_loop.projects.discovery import discover_project_set
from task_closed_loop.store.task_store import iso_week, open_task_store
from task_closed_loop.tasks.skill_chain_models import Project, ProjectScope


def build_locked_production_pipeline(*, config: dict, project_root: Path, minimum_tasks: int, max_rounds: int, logger=None):
    root = Path(project_root).resolve()
    cli_root = cli_project_root(config, root).resolve()
    provider = LazyTaskRuntimeProvider(config=config, project_root=root, minimum_tasks=minimum_tasks)
    artifacts = YamlProductionArtifactWriter(cli_root / "generated")
    return LockedProductionPipeline(
        cli_project=DefaultCliProjectManager(config=config, project_root=root, logger=logger),
        resource_analysis=CliResourceCapabilityAnalyzer(config=config, project_root=root, logger=logger),
        task_generation=LlmInitialTaskGenerator(runtime_provider=provider),
        task_audit=LlmTaskAuditor(runtime_provider=provider, rejection_writer=artifacts),
        task_count=QualifiedBusinessTaskCountPolicy(minimum=minimum_tasks),
        task_dimensions=LlmTaskDimensionGenerator(runtime_provider=provider),
        task_regeneration=LlmTaskRegenerator(runtime_provider=provider),
        artifacts=artifacts,
        max_rounds=max_rounds,
    )


@dataclass
class ProjectPipeline:
    """One project's own run of the unchanged 7-stage pipeline."""

    project: Project
    pipeline: LockedProductionPipeline
    generator: ProjectChainTaskGenerator
    artifacts_dir: Path


@dataclass
class ProjectChainRun:
    cache: ProjectStage2Cache
    store: object
    week: str
    items: list[ProjectPipeline]
    project_set: object = None


def first_step_mode(config: dict) -> str:
    first_step = ((config or {}).get("task_generation") or {}).get("first_step") or {}
    return str(first_step.get("mode") or "skill_chain").strip() or "skill_chain"


async def build_project_chain_run(
    *,
    config: dict,
    project_root: Path,
    minimum_tasks: int,
    max_rounds: int,
    logger=None,
) -> ProjectChainRun:
    """One pipeline per project: each needs its own reality, so each gets its own run.

    Stage 1 and Stage 2 run once up front — the directories and functions Stage 2 scans
    do not change per project, only who may see the result — and then each resource is
    assigned to the project(s) it belongs to. Every per-project pipeline still executes
    Stage 1 (idempotent reuse) and Stage 2 (served from the cache), so the locked stage
    order is unchanged.
    """

    root = Path(project_root).resolve()
    cli_root = cli_project_root(config, root).resolve()
    store = open_task_store(config)
    week = iso_week()
    cache = ProjectStage2Cache(logger=logger)
    provider = LazyTaskRuntimeProvider(
        config=config, project_root=root, minimum_tasks=minimum_tasks
    )
    base_analyzer = CliResourceCapabilityAnalyzer(
        config=config, project_root=root, logger=logger
    )

    cli_manager = DefaultCliProjectManager(config=config, project_root=root, logger=logger)
    cli_project = cli_manager.ensure_project()
    cache.materialize(base_analyzer, cli_project.root)

    components = await provider.validate_task()
    # Step 3: the projects come out of the resources themselves.
    project_set = await discover_project_set(
        reasoner=components.task_llm,
        resource_briefs=cache.resolver.resource_briefs(cache.materialized.resources),
        function_names=cache.resolver.capability_names(cache.materialized.capabilities),
        state_dir=Path(cli_project.root) / "state",
        logger=logger,
    )
    scopes = cache.apply_projects(project_set)
    owning_projects = [scope.project for scope in scopes]
    multi = len(owning_projects) > 1

    items: list[ProjectPipeline] = []
    for project in owning_projects:
        artifacts_dir = (
            cli_root / "generated" / project.project_id if multi else cli_root / "generated"
        )
        artifacts = YamlProductionArtifactWriter(artifacts_dir)
        generator = ProjectChainTaskGenerator(
            runtime_provider=provider,
            project_id=project.project_id,
            scope_provider=lambda pid=project.project_id, proj=project: _scope_or_empty(
                cache, pid, proj
            ),
            store=store,
            week=week,
            logger=logger,
        )
        pipeline = LockedProductionPipeline(
            cli_project=cli_manager,
            resource_analysis=CachedProjectScopedAnalyzer(
                inner=base_analyzer, cache=cache, project_id=project.project_id
            ),
            task_generation=generator,
            task_audit=LlmTaskAuditor(runtime_provider=provider, rejection_writer=artifacts),
            task_count=QualifiedBusinessTaskCountPolicy(minimum=minimum_tasks),
            task_dimensions=LlmTaskDimensionGenerator(runtime_provider=provider),
            # Stage 7 stays on the chain: a supplementary task needs the same lineage.
            task_regeneration=ProjectChainTaskRegenerator(
                generator=generator, logger=logger
            ),
            artifacts=artifacts,
            max_rounds=max_rounds,
        )
        items.append(
            ProjectPipeline(
                project=project,
                pipeline=pipeline,
                generator=generator,
                artifacts_dir=artifacts_dir,
            )
        )

    return ProjectChainRun(
        cache=cache,
        store=store,
        week=week,
        items=items,
        project_set=project_set,
    )


def _scope_or_empty(cache: ProjectStage2Cache, project_id: str, project: Project) -> ProjectScope:
    try:
        return cache.scope(project_id)
    except KeyError:
        # Configured, but Stage 2 produced nothing it owns (e.g. its function failed).
        # An empty scope is honest; the chain then reports zero instead of crashing.
        return ProjectScope(project=project)
