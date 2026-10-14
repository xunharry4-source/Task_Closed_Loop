from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path

from task_closed_loop.architecture import load_locked_architecture_contract
from task_closed_loop.app.orchestrator import RuntimeCycleInput, RuntimeOrchestrator
from task_closed_loop.config import load_project_config
from task_closed_loop.diagnostics.artifacts import RunArtifactStore
from task_closed_loop.diagnostics.logging import (
    configure_runtime_logging,
    create_flow_id,
    model_label,
    set_flow_id,
)
from task_closed_loop.implementations.composition import (
    build_locked_production_pipeline,
    build_project_chain_run,
    first_step_mode,
)
from task_closed_loop.implementations.task_persistence import save_project_tasks
from task_closed_loop.llm import build_llm
from task_closed_loop.reality.builder import RealityEngine
from task_closed_loop.tasks.continuity import TaskContinuityEngine
from task_closed_loop.tasks.generator import TaskGenerationEngine
from task_closed_loop.task_inputs import load_task_input_bundle


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _task_payload(task) -> dict:
    return {
        "task_id": task.task_id,
        "task_identity": task.task_identity,
        "description": task.description,
        "user_value": task.user_value,
        "expected_result": task.expected_reality_result,
        "execution_steps": list(task.execution_steps),
        "reality_basis": task.reality_basis,
        "status": task.status,
        "metadata": task.metadata,
    }


def _print_tasks(tasks) -> None:
    print("New Tasks:")
    if not tasks:
        print("[]")
        return
    for index, task in enumerate(tasks, start=1):
        metadata = task.metadata or {}
        print()
        header = f"Task {index}"
        theme = str(metadata.get("theme") or "")
        tier = str(metadata.get("task_tier") or "")
        if theme or tier:
            header += f"  [{theme}{' / ' if theme and tier else ''}{tier}]"
        print(header)
        if metadata.get("entity_id"):
            print("所属项目：" + str(metadata["entity_id"]))
        print("任务：" + task.description)
        print("对用户的价值：" + task.user_value)
        print("需要得到什么结果：" + task.expected_reality_result)
        print("执行步骤：")
        for step_index, step in enumerate(task.execution_steps, start=1):
            print(f"{step_index}. {step}")


async def _validate_reasoner(reasoner) -> None:
    validate = getattr(reasoner, "validate_connection", None)
    if validate is not None:
        await validate()


async def _run_project_chain(*, config, root, logger, artifacts, flow_id, minimum_tasks, max_rounds) -> list:
    """SKILL first step: one pipeline run per project, each with its own reality.

    Stages 4-7 and the artifact writers are the unchanged implementations; only the
    first step differs, and each project is isolated from every other.
    """

    chain = await build_project_chain_run(
        config=config,
        project_root=root,
        minimum_tasks=minimum_tasks,
        max_rounds=max_rounds,
        logger=logger,
    )
    if not chain.items:
        raise RuntimeError(
            "没有任何数据源或功能归属到已声明的项目；"
            "请在 config/preflight_sources.yml 的条目上填写 entities。"
        )

    assignment = chain.assignment
    logger.info(
        "runtime.projects week=%s projects=%s store=%s",
        chain.week,
        [item.project.project_id for item in chain.items],
        getattr(chain.store, "path", None),
    )
    if assignment is not None:
        artifacts.write_json(
            "project_assignment.json",
            {
                "flow_id": flow_id,
                "assignments": assignment.to_payload(),
                "origin": dict(assignment.origin),
                "unassigned_resources": list(assignment.unassigned()),
            },
        )
        if assignment.unassigned():
            logger.warning(
                "runtime.projects 未归属的资源（不会产生任务）：%s",
                list(assignment.unassigned()),
            )

    produced: list = []
    try:
        for item in chain.items:
            project_id = item.project.project_id
            logger.info("runtime.project start %s", project_id)
            production = await item.pipeline.run()
            tasks = list(production.tasks)
            report = save_project_tasks(
                store=chain.store,
                project=item.project,
                tasks=tasks,
                logger=logger,
            )
            produced.extend(tasks)
            artifacts.write_json(
                f"project_{project_id}.json",
                {
                    "flow_id": flow_id,
                    "project": asdict(item.project),
                    "week": chain.week,
                    "reality_id": production.reality.reality_id,
                    "rounds": production.rounds,
                    "stage_order": production.stage_order,
                    "task_count": len(tasks),
                    "artifacts_dir": str(item.artifacts_dir),
                    "chain": _chain_payload(item.generator.chain_trace),
                    "task_store": {
                        "inserted": report.inserted,
                        "repeated": report.repeated,
                        "shelved": report.shelved,
                        "skipped": report.skipped,
                    },
                    "tasks": [_task_payload(task) for task in tasks],
                },
            )
            logger.info(
                "runtime.project done %s tasks=%d rounds=%d",
                project_id,
                len(tasks),
                production.rounds,
            )
    finally:
        if chain.store is not None:
            chain.store.close()

    return produced


def _chain_payload(chain_trace) -> dict:
    return {
        "reality_id": chain_trace.reality_id,
        "problems": [asdict(record) for record in chain_trace.problems],
        "value_opportunities": [asdict(record) for record in chain_trace.values],
        "capability_voids": [asdict(record) for record in chain_trace.demands],
        "theme_plan": asdict(chain_trace.theme_plan) if chain_trace.theme_plan else None,
        "themes_asked": list(chain_trace.themes_asked),
        "candidate_counts": dict(chain_trace.candidate_counts),
        "dropped_records": dict(chain_trace.dropped_records),
        "dropped_candidates": dict(chain_trace.dropped_candidates),
        "errors": dict(chain_trace.errors),
    }


async def _run(*, use_test_resources: bool) -> None:
    flow_id = set_flow_id(create_flow_id())
    root = project_root()
    load_locked_architecture_contract(root)
    logger = configure_runtime_logging({})
    artifacts = RunArtifactStore(
        root, flow_id, log_root=os.getenv("TASK_CLOSED_LOOP_LOG_DIR")
    )
    artifacts.write_json(
        "run_started.json",
        {"flow_id": flow_id, "use_test_resources": use_test_resources},
    )

    try:
        config = load_project_config(root)
        configure_runtime_logging(config)
        task_generation_cfg = config.get("task_generation", {})
        coverage_cfg = task_generation_cfg.get("coverage_expansion", {})
        pipeline_cfg = task_generation_cfg.get("production_pipeline", {})
        min_qualified_tasks = (
            int(coverage_cfg.get("min_qualified_tasks", 5))
            if coverage_cfg.get("enabled", True)
            else 0
        )

        production = None
        if not use_test_resources and first_step_mode(config) == "skill_chain":
            if not bool(pipeline_cfg.get("enabled", True)):
                raise RuntimeError("正式生产模式必须启用锁定的 7-Stage Production Pipeline。")
            produced_tasks = await _run_project_chain(
                config=config,
                root=root,
                logger=logger,
                artifacts=artifacts,
                flow_id=flow_id,
                minimum_tasks=min_qualified_tasks,
                max_rounds=int(pipeline_cfg.get("max_rounds", 3)),
            )
            artifacts.write_json(
                "task_list.json",
                {"flow_id": flow_id, "tasks": [_task_payload(t) for t in produced_tasks]},
            )
            _print_tasks(produced_tasks)
            return

        if not use_test_resources:
            if not bool(pipeline_cfg.get("enabled", True)):
                raise RuntimeError("正式生产模式必须启用锁定的 7-Stage Production Pipeline。")
            # Formal mode: Stage 1-2 run before Task/Audit LLMs are even built.
            # LazyTaskRuntimeProvider creates Task API/CLI only when Stage 3 begins.
            pipeline = build_locked_production_pipeline(
                config=config,
                project_root=root,
                minimum_tasks=min_qualified_tasks,
                max_rounds=int(pipeline_cfg.get("max_rounds", 3)),
                logger=logger,
            )
            try:
                production = await pipeline.run()
            except Exception:
                # If Stage 1 completed but a later stage failed, preserve its state for
                # operational diagnosis without re-running the stage.
                cli_root = root / str(
                    ((config.get("execution") or {}).get("capability_project") or {}).get(
                        "workspace_path", "cli_project"
                    )
                )
                if cli_root.exists():
                    artifacts.write_json(
                        "stage_1_cli_project.json",
                        {"flow_id": flow_id, "path": str(cli_root.resolve())},
                    )
                raise
            result = production.last_cycle
            produced_tasks = list(production.tasks)
            stage1 = next(record for record in production.stages if record.stage == 1)
            stage2 = next(record for record in production.stages if record.stage == 2)
            artifacts.write_json("stage_1_cli_project.json", {"flow_id": flow_id, **stage1.detail})
            artifacts.write_json("stage_2_materialization.json", {"flow_id": flow_id, **stage2.detail})
            artifacts.write_json(
                "task_production_pipeline.json",
                {
                    "flow_id": flow_id,
                    **production.to_payload(),
                    "dimensions": [asdict(d) for d in production.dimensions],
                },
            )
            logger.info(
                "runtime.pipeline stages=%s rounds=%d tasks=%d",
                production.stage_order, production.rounds, len(produced_tasks),
            )
        else:
            # Developer Task-only mode: prepared standard Resource/Capability fixtures.
            # It intentionally does not pretend to be the formal seven-stage entry.
            task_inputs_cfg = config.get("task_inputs", {})
            input_profile = task_inputs_cfg.get("test", {})
            bundle = load_task_input_bundle(
                input_profile.get("resources_file", ""),
                input_profile.get("capabilities_file", ""),
                project_root=root,
            )
            task_llm = build_llm(config, root, profile="task")
            audit_llm = build_llm(config, root, profile="audit")
            logger.info(
                "runtime.models task=%s audit=%s",
                model_label(task_llm), model_label(audit_llm),
            )
            await _validate_reasoner(task_llm)
            await _validate_reasoner(audit_llm)
            need_cfg = task_generation_cfg.get("need_opportunity_discovery", {})
            proliferation_cfg = task_generation_cfg.get("task_proliferation", {})
            runtime = RuntimeOrchestrator(
                reality_engine=RealityEngine(task_llm),
                task_continuity=TaskContinuityEngine(task_llm),
                task_generation=TaskGenerationEngine(
                    task_reasoner=task_llm,
                    audit_reasoner=audit_llm,
                    coverage_expansion_min_tasks=min_qualified_tasks,
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
            logger.info(
                "runtime.task_inputs resources=%s capabilities=%s resource_count=%d capability_count=%d",
                bundle.resources_path, bundle.capabilities_path,
                len(bundle.resources), len(bundle.capabilities),
            )
            result = await runtime.run_cycle(
                RuntimeCycleInput(
                    resources=list(bundle.resources),
                    capabilities=list(bundle.capabilities),
                )
            )
            produced_tasks = list(result.new_tasks)

        trace = result.task_generation.trace
        logger.info(
            "runtime.summary reality_id=%s discoveries=%d discovered=%d accepted=%d tasks=%d observation_tasks=%d",
            result.reality.reality_id,
            len(trace.discovery_signals),
            len(result.task_generation.discovered_candidates),
            len(result.task_generation.accepted_candidates),
            len(produced_tasks),
            len(result.observation_tasks),
        )

        artifacts.write_json("observation_acquisition.json", {
            "flow_id": flow_id,
            "attempted": trace.observation_acquisition_attempted,
            "acquisition_ids": trace.observation_acquisition_ids,
            "candidate_ids": trace.observation_acquisition_candidate_ids,
            "suppressed": trace.observation_acquisition_suppressed,
            "tasks": [_task_payload(task) for task in result.observation_tasks],
        })
        artifacts.write_json("discovery_signals.json", {
            "flow_id": flow_id,
            "discoveries": [asdict(signal) for signal in trace.discovery_signals],
            "rejected_discovery_ids": trace.rejected_discovery_ids,
            "rejected_discovery_reasons": trace.rejected_discovery_reasons,
            "discovery_error": trace.discovery_error,
            "seed_validation_errors": trace.seed_validation_errors,
        })
        artifacts.write_json("task_proliferation.json", {
            "flow_id": flow_id,
            "attempted": trace.proliferation_attempted,
            "succeeded": trace.proliferation_succeeded,
            "error": trace.proliferation_error,
            "outcomes": [asdict(outcome) for outcome in trace.proliferation_outcomes],
            "seeds": [asdict(seed) for seed in trace.proliferation_seeds],
            "zero_seed_outcome_ids": trace.proliferation_zero_seed_outcome_ids,
        })
        artifacts.write_json("coverage_dimensions.json", {
            "flow_id": flow_id,
            "trigger_threshold": min_qualified_tasks,
            "attempted": trace.coverage_expansion_attempted,
            "succeeded": trace.coverage_expansion_succeeded,
            "error": trace.coverage_expansion_error,
            "first_pass_seeds": [asdict(seed) for seed in trace.discovery_seeds],
            "rejected_candidate_contexts": [asdict(c) for c in trace.rejected_candidate_contexts],
            "dimensions": [asdict(d) for d in trace.coverage_expansion_dimensions],
            "coverage_second_pass_seeds": [asdict(s) for s in trace.coverage_expansion_seeds],
            "seed_materialization_errors": trace.seed_materialization_errors,
            "second_pass_candidate_ids": trace.coverage_expansion_second_pass_candidate_ids,
        })
        artifacts.write_json("task_list.json", {
            "flow_id": flow_id,
            "tasks": [_task_payload(task) for task in produced_tasks],
        })
        artifacts.write_json("run_summary.json", {
            "flow_id": flow_id,
            "reality_id": result.reality.reality_id,
            "observation_task_count": len(result.observation_tasks),
            "discovery_signal_count": len(trace.discovery_signals),
            "task_count": len(produced_tasks),
            "pipeline": production.to_payload() if production is not None else None,
            "proliferation_seed_count": len(trace.proliferation_seeds),
            "rejected_candidate_count": len(trace.rejected_candidate_contexts),
        })

        print("Current Reality:", result.reality.current_facts)
        _print_tasks(produced_tasks)

    except Exception as exc:
        artifacts.write_json("run_failure.json", {
            "flow_id": flow_id,
            "error_type": type(exc).__name__,
            "error": str(exc),
        })
        logger.exception(
            "runtime.failed flow_id=%s error_type=%s", flow_id, type(exc).__name__
        )
        raise

async def main() -> None:
    """Formal Task runtime: consumes files already produced by Preflight."""
    await _run(
        use_test_resources=False,
    )


async def test_main() -> None:
    """
    Developer Task-layer test runtime.

    Reads only hand-authored/prepared Task input contracts:
        config/task_layer_test/resources.yml
        config/task_layer_test/capabilities.yml

    It intentionally does not test Preflight resource/capability analysis.
    """
    await _run(
        use_test_resources=True,
    )
