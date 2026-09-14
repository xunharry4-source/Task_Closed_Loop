"""Compatibility wrappers for Stage 1-2.

Formal production does not depend on this module. Runtime composes the frozen pipeline
through contracts + implementations. Existing callers may keep these functions while
behavior lives only under ``implementations/``.
"""
from __future__ import annotations
from pathlib import Path
from typing import Iterable

from task_closed_loop.capability_runtime.cli.base import CliEngineAdapter
from task_closed_loop.capability_runtime.workspace import CliProjectStructureError
from task_closed_loop.contracts import CliProjectResult as CliProjectStageResult
from task_closed_loop.contracts import ResourceCapabilityResult
from task_closed_loop.implementations.cli_project import (
    DefaultCliProjectManager,
    capability_project_config,
    cli_project_root,
    cli_project_template_root,
)
from task_closed_loop.implementations.resource_analysis import CliResourceCapabilityAnalyzer

DEFAULT_CLI_PROJECT_PATH = "cli_project"
DEFAULT_CLI_PROJECT_TEMPLATE = "cli_project_template"


class MaterializationStageResult:
    """Compatibility view over ResourceCapabilityResult."""
    def __init__(self, result: ResourceCapabilityResult):
        self.resources_path = result.resources_path
        self.capabilities_path = result.capabilities_path
        self.resource_analysis_path = result.resource_analysis_path
        self.function_analysis_path = result.function_analysis_path
        self.local_resource_count = result.local_resource_count
        self.remote_resource_count = result.remote_resource_count
        self.function_count = result.function_count
        self.cli_engine = result.cli_engine

    @property
    def source_count(self) -> int:
        return self.local_resource_count + self.remote_resource_count + self.function_count


def run_stage_1_cli_project(
    config: dict,
    project_root: Path,
    *,
    logger=None,
    adapters: Iterable[CliEngineAdapter] | None = None,
    explicit_engine: str | None = None,
):
    return DefaultCliProjectManager(
        config=config,
        project_root=project_root,
        logger=logger,
        adapters=adapters,
        explicit_engine=explicit_engine,
    ).ensure_project()


def run_stage_2_materialization(
    config: dict,
    project_root: Path,
    cli_root: Path,
    *,
    logger=None,
    adapters: Iterable[CliEngineAdapter] | None = None,
):
    result = CliResourceCapabilityAnalyzer(
        config=config,
        project_root=project_root,
        logger=logger,
        adapters=adapters,
    ).analyze(cli_root)
    return MaterializationStageResult(result)


__all__ = [
    "CliProjectStageResult",
    "CliProjectStructureError",
    "MaterializationStageResult",
    "capability_project_config",
    "cli_project_root",
    "cli_project_template_root",
    "run_stage_1_cli_project",
    "run_stage_2_materialization",
]
