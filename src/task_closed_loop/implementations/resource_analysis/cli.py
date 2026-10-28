from __future__ import annotations

from pathlib import Path
from typing import Iterable

from task_closed_loop.capability_runtime.cli.base import CliEngineAdapter
from task_closed_loop.contracts import ResourceCapabilityResult
from task_closed_loop.implementations.cli_project import capability_project_config
from task_closed_loop.llm.prompt_registry import PromptRegistry
from task_closed_loop.cli_choice import configured_cli_engine
from task_closed_loop.preflight.cli_preflight import (
    ANALYZE_AUTO,
    ANALYZE_NEVER,
    CliPreflightEngine,
    analysis_mode,
    PreflightSourceConfigurationError,
    load_preflight_inputs,
)
from task_closed_loop.task_inputs import load_task_input_bundle


class CliResourceCapabilityAnalyzer:
    """Stage 2 implementation. CLI code lives and evolves inside cli_project/."""

    def __init__(
        self,
        *,
        config: dict,
        project_root: Path,
        logger=None,
        adapters: Iterable[CliEngineAdapter] | None = None,
    ):
        self.config = config
        self.project_root = Path(project_root).resolve()
        self.logger = logger
        self.adapters = list(adapters) if adapters is not None else None

    def analyze(self, cli_project: Path) -> ResourceCapabilityResult:
        inputs = load_preflight_inputs(self.config, project_root=self.project_root)
        section = (self.config or {}).get("preflight_inputs") or {}
        if not section.get("enabled", True):
            raise PreflightSourceConfigurationError(
                "Stage 2 是正式生产硬阶段，preflight_inputs.enabled=false 不允许进入 Stage 3。"
            )
        if inputs.total_count == 0:
            raise PreflightSourceConfigurationError(
                "第一步没有配置任何工作目录或功能：请在 config/preflight_sources.yml 的 "
                "directories / functions 里至少写一项。"
            )

        capability_cfg = capability_project_config(self.config)
        prompt_text = PromptRegistry(
            self.project_root,
            (self.config.get("llm", {}) or {}).get(
                "prompt_manifest", "src/task_closed_loop/prompts/manifest.yml"
            ),
        ).get("preflight_source_analysis")

        engine = CliPreflightEngine(
            project_root=Path(cli_project).resolve(),
            prompt_text=prompt_text,
            adapters=self.adapters,
            preferred_engines=list(
                capability_cfg.get(
                    "allowed_cli_engines", ["codex_cli", "gemini_cli", "claude_cli"]
                )
            ),
        )
        # Step 2 initializes the data. It runs when the saved templates do not cover
        # the configuration (or when asked to re-initialize), and is skipped otherwise.
        mode = analysis_mode(self.config)
        engine_choice = configured_cli_engine(self.config) or None
        if mode == ANALYZE_NEVER:
            output = engine.reuse_saved(inputs)
        else:
            # auto: initialize only what has no saved data yet. always: re-initialize all.
            output = engine.materialize(
                inputs,
                explicit_engine=engine_choice,
                reuse_saved=(mode == ANALYZE_AUTO),
            )
        bundle = load_task_input_bundle(
            output.resources_path,
            output.capabilities_path,
            project_root=self.project_root,
        )

        if self.logger is not None:
            self.logger.info(
                "stage2.materialization local=%d remote=%d functions=%d engine=%s resources=%s capabilities=%s",
                len(inputs.local_resources),
                len(inputs.remote_resources),
                len(inputs.functions),
                output.cli_engine,
                output.resources_path,
                output.capabilities_path,
            )
        return ResourceCapabilityResult(
            cli_root=Path(cli_project).resolve(),
            resources_path=output.resources_path,
            capabilities_path=output.capabilities_path,
            resource_analysis_path=output.resource_analysis_path,
            function_analysis_path=output.function_analysis_path,
            resources=tuple(bundle.resources),
            capabilities=tuple(bundle.capabilities),
            local_resource_count=len(inputs.local_resources),
            remote_resource_count=len(inputs.remote_resources),
            function_count=len(inputs.functions),
            cli_engine=output.cli_engine,
        )
