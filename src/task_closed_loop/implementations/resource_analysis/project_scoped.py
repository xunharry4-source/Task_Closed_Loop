"""Stage 2 once, then one project's slice of it per pipeline run.

Each project needs its own reality (candidates are bound to one `reality_id`), so each
project gets its own pipeline run. Stage 2 itself must not be repeated per project: its
CLI subprocess scans the same directories and queries the same functions no matter who
asks. So the real analyzer runs on the first pipeline and every later project is served
from the cache, filtered to what that project owns.
"""

from __future__ import annotations

from pathlib import Path

from task_closed_loop.contracts import ResourceCapabilityResult
from task_closed_loop.projects.grouping import ProjectScopeResolver
from task_closed_loop.tasks.skill_chain_models import ProjectScope


class ProjectStage2Cache:
    """Holds the single Stage 2 materialization and the per-project split of it."""

    def __init__(self, *, logger=None):
        self.logger = logger
        self._result: ResourceCapabilityResult | None = None
        self._resolver: ProjectScopeResolver | None = None
        self._scopes: dict[str, ProjectScope] = {}

    @property
    def materialized(self) -> ResourceCapabilityResult | None:
        return self._result

    def materialize(self, analyzer, cli_project: Path) -> ResourceCapabilityResult:
        if self._result is not None:
            return self._result
        result = analyzer.analyze(cli_project)
        self._resolver = ProjectScopeResolver(
            generated_dir=Path(result.resources_path).parent
        )
        self._result = result
        return result

    @property
    def resolver(self) -> ProjectScopeResolver:
        if self._resolver is None:
            raise RuntimeError("Stage 2 还没有执行，拿不到资源来源信息。")
        return self._resolver

    def apply_projects(self, project_set) -> tuple[ProjectScope, ...]:
        """Split the materialized output across the projects step 3 produced."""

        if self._result is None:
            raise RuntimeError("Stage 2 还没有执行，无法按项目切分。")
        scopes = self.resolver.scopes(
            self._result.resources, self._result.capabilities, project_set
        )
        self._scopes = {scope.project.project_id: scope for scope in scopes}
        if self.logger is not None:
            self.logger.info(
                "stage2.projects %s",
                {
                    scope.project.project_id: {
                        "resources": [r.resource_id for r in scope.resources],
                        "functions": [
                            brief.get("function") for brief in scope.capability_briefs
                        ],
                    }
                    for scope in scopes
                },
            )
        return tuple(scopes)

    def project_ids(self) -> tuple[str, ...]:
        return tuple(self._scopes)

    def scope(self, project_id: str) -> ProjectScope:
        try:
            return self._scopes[project_id]
        except KeyError as exc:
            raise KeyError(
                f"项目 '{project_id}' 在本轮 Stage 2 产物里没有任何资源或功能。"
            ) from exc

    def scopes(self) -> tuple[ProjectScope, ...]:
        return tuple(self._scopes.values())

    def project_result(self, project_id: str) -> ResourceCapabilityResult:
        if self._result is None:
            raise RuntimeError("Stage 2 还没有执行，无法按项目取结果。")
        scope = self.scope(project_id)
        base = self._result
        return ResourceCapabilityResult(
            cli_root=base.cli_root,
            resources_path=base.resources_path,
            capabilities_path=base.capabilities_path,
            resource_analysis_path=base.resource_analysis_path,
            function_analysis_path=base.function_analysis_path,
            resources=tuple(scope.resources),
            capabilities=tuple(scope.capabilities),
            local_resource_count=base.local_resource_count,
            remote_resource_count=base.remote_resource_count,
            function_count=base.function_count,
            cli_engine=base.cli_engine,
        )


class CachedProjectScopedAnalyzer:
    """Stage 2 implementation for one project's pipeline run."""

    def __init__(self, *, inner, cache: ProjectStage2Cache, project_id: str):
        self.inner = inner
        self.cache = cache
        self.project_id = project_id

    def analyze(self, cli_project) -> ResourceCapabilityResult:
        self.cache.materialize(self.inner, cli_project)
        return self.cache.project_result(self.project_id)
