"""Frozen seven-stage production pipeline.

This module is the architecture boundary. It imports production *contracts only*.
Concrete CLI/LLM/file implementations are injected by the composition root.
Changing behavior belongs in ``implementations/`` or ``infrastructure/``; changing
this file is an architecture change and must bump the architecture contract version.
"""

from __future__ import annotations

from task_closed_loop.contracts import (
    CliProjectManager,
    InitialTaskGenerator,
    PipelineCycleView,
    ProductionArtifactWriter,
    ProductionPipelineResult,
    ResourceCapabilityAnalyzer,
    StageRecord,
    TaskAuditor,
    TaskCountPolicy,
    TaskDimensionGenerator,
    TaskRegenerator,
)


class ProductionStageError(RuntimeError):
    """A frozen production stage failed; later stages must not run."""


class LockedProductionPipeline:
    """The immutable 7-stage architecture.

    Stage 1  CLI Project check/repair
    Stage 2  Resource + Function analysis/materialization
    Stage 3  Initial task generation (no audit, no dimensions)
    Stage 4  Independent task audit
    Stage 5  Count accepted business tasks
    Stage 6  Generate dimensions only if too few
    Stage 7  Regenerate using dimensions, then return to Stage 4
    """

    def __init__(
        self,
        *,
        cli_project: CliProjectManager,
        resource_analysis: ResourceCapabilityAnalyzer,
        task_generation: InitialTaskGenerator,
        task_audit: TaskAuditor,
        task_count: TaskCountPolicy,
        task_dimensions: TaskDimensionGenerator,
        task_regeneration: TaskRegenerator,
        artifacts: ProductionArtifactWriter,
        max_rounds: int = 3,
    ):
        self._cli_project = cli_project
        self._resource_analysis = resource_analysis
        self._task_generation = task_generation
        self._task_audit = task_audit
        self._task_count = task_count
        self._task_dimensions = task_dimensions
        self._task_regeneration = task_regeneration
        self._artifacts = artifacts
        self._max_rounds = max(1, int(max_rounds))

    async def run(self) -> ProductionPipelineResult:
        stages: list[StageRecord] = []

        # Stage 1 ------------------------------------------------------------
        cli_project = self._cli_project.ensure_project()
        stages.append(
            StageRecord(
                1,
                "cli_project_check",
                {
                    "path": str(cli_project.root),
                    "created_from_template": cli_project.created,
                    "repaired_by_cli": cli_project.repaired_by_cli,
                    "repair_engine": cli_project.repair_engine,
                },
            )
        )

        # Stage 2 ------------------------------------------------------------
        materialized = self._resource_analysis.analyze(cli_project.root)
        stages.append(
            StageRecord(
                2,
                "resource_capability_materialization",
                {
                    "local_resource_count": materialized.local_resource_count,
                    "remote_resource_count": materialized.remote_resource_count,
                    "function_count": materialized.function_count,
                    "cli_engine": materialized.cli_engine,
                    "resource_analysis_file": str(materialized.resource_analysis_path),
                    "function_analysis_file": str(materialized.function_analysis_path),
                    "resources_file": str(materialized.resources_path),
                    "capabilities_file": str(materialized.capabilities_path),
                },
            )
        )

        # Stage 3 ------------------------------------------------------------
        base_batch = await self._task_generation.generate(
            materialized.resources,
            materialized.capabilities,
        )
        initial_path = self._artifacts.write_initial(
            base_batch.draft.discovered_candidates
        )
        stages.append(
            StageRecord(
                3,
                "initial_task_generation",
                {
                    "candidate_count": len(base_batch.draft.discovered_candidates),
                    "used_task_dimensions": False,
                    "used_thinking_dimensions": False,
                    "task_file": str(initial_path) if initial_path else None,
                },
            )
        )

        # Stage 4 ------------------------------------------------------------
        audit = await self._task_audit.audit(base_batch)
        tasks = list(audit.tasks)
        accepted = list(audit.accepted_candidates)
        audited_path = self._artifacts.write_audited(tasks, round_number=0)
        stages.append(
            StageRecord(
                4,
                "task_audit",
                {
                    "round": 0,
                    "accepted_candidate_count": len(audit.accepted_candidates),
                    "qualified_task_count": len(audit.tasks),
                    "rejected_candidate_count": audit.rejected_count,
                    "task_file": str(audited_path) if audited_path else None,
                },
            )
        )

        all_dimensions: list = []
        rounds = 0
        final_audit = audit

        while True:
            # Stage 5 --------------------------------------------------------
            count = self._task_count.evaluate(tasks)
            stages.append(
                StageRecord(
                    5,
                    "qualified_task_count_check",
                    {
                        "qualified_task_count": len(count.qualified_tasks),
                        "threshold": count.threshold,
                        "too_few": count.too_few,
                        "round": rounds,
                    },
                )
            )
            if not count.too_few:
                break
            if rounds >= self._max_rounds:
                stages.append(
                    StageRecord(
                        5,
                        "task_count_check_exhausted",
                        {
                            "qualified_task_count": len(count.qualified_tasks),
                            "threshold": count.threshold,
                            "max_rounds": self._max_rounds,
                        },
                    )
                )
                break

            # Stage 6 --------------------------------------------------------
            try:
                dimension_result = await self._task_dimensions.generate(
                    base_batch=base_batch,
                    audit_result=final_audit,
                    accepted_candidates=accepted,
                    round_number=rounds + 1,
                )
            except Exception as exc:  # implementation failure, architecture stops
                raise ProductionStageError(
                    f"Stage 6 Task Dimension 生成失败：{type(exc).__name__}: {exc}"
                ) from exc
            dimensions = list(dimension_result.dimensions)
            all_dimensions.extend(dimensions)
            dimension_path = self._artifacts.write_dimensions(all_dimensions)
            stages.append(
                StageRecord(
                    6,
                    "task_dimension_generation",
                    {
                        "dimension_count": len(dimensions),
                        "round": rounds + 1,
                        "dimensions_file": str(dimension_path) if dimension_path else None,
                    },
                )
            )
            if not dimensions:
                break

            # Stage 7 --------------------------------------------------------
            rounds += 1
            regenerated = await self._task_regeneration.regenerate(
                base_batch=base_batch,
                current_tasks=tasks,
                accepted_candidates=accepted,
                dimensions=all_dimensions,
                round_number=rounds,
            )
            regeneration_path = self._artifacts.write_regenerated(
                regenerated.draft.discovered_candidates,
                round_number=rounds,
            )
            stages.append(
                StageRecord(
                    7,
                    "task_regeneration",
                    {
                        "round": rounds,
                        "dimension_count": len(all_dimensions),
                        "candidate_count": len(regenerated.draft.discovered_candidates),
                        "task_file": str(regeneration_path) if regeneration_path else None,
                    },
                )
            )

            # Locked edge: every Stage 7 result returns to Stage 4.
            supplemental_audit = await self._task_audit.audit(regenerated)
            tasks = _merge_tasks(tasks, list(supplemental_audit.tasks))
            accepted = _merge_candidates(
                accepted,
                list(supplemental_audit.accepted_candidates),
            )
            final_audit = supplemental_audit
            audited_path = self._artifacts.write_audited(tasks, round_number=rounds)
            stages.append(
                StageRecord(
                    4,
                    "task_audit",
                    {
                        "round": rounds,
                        "accepted_candidate_count": len(
                            supplemental_audit.accepted_candidates
                        ),
                        "qualified_task_count": len(supplemental_audit.tasks),
                        "rejected_candidate_count": supplemental_audit.rejected_count,
                        "task_file": str(audited_path) if audited_path else None,
                    },
                )
            )

        final_path = self._artifacts.write_final(tasks)
        if stages:
            stages[-1].detail.setdefault(
                "final_task_file",
                str(final_path) if final_path else None,
            )

        cycle_view = PipelineCycleView(
            reality=base_batch.prepared.reality,
            effective_existing_tasks=list(base_batch.prepared.effective_existing_tasks),
            task_generation=final_audit.generation,
        )
        return ProductionPipelineResult(
            reality=base_batch.prepared.reality,
            tasks=tasks,
            rounds=rounds,
            stages=stages,
            dimensions=all_dimensions,
            last_cycle=cycle_view,
            cli_project=cli_project.root,
            resources_path=materialized.resources_path,
            capabilities_path=materialized.capabilities_path,
        )


def _work_key(task) -> tuple:
    anchors = tuple(
        sorted(
            str(value)
            for value in (task.metadata.get("identity_anchor_refs") or ())
        )
    )
    identity = str(task.task_identity).strip()
    if identity:
        return (identity, anchors)
    return ("task_id", str(task.task_id))


def _merge_tasks(existing: list, incoming: list) -> list:
    seen = {_work_key(task) for task in existing}
    merged = list(existing)
    for task in incoming:
        key = _work_key(task)
        if key in seen:
            continue
        seen.add(key)
        merged.append(task)
    return merged


def _merge_candidates(existing: list, incoming: list) -> list:
    seen = {str(candidate.candidate_id) for candidate in existing}
    merged = list(existing)
    for candidate in incoming:
        candidate_id = str(candidate.candidate_id)
        if candidate_id in seen:
            continue
        seen.add(candidate_id)
        merged.append(candidate)
    return merged
