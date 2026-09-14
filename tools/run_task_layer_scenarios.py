from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from task_closed_loop.app.orchestrator import RuntimeCycleInput, RuntimeOrchestrator
from task_closed_loop.reality.builder import RealityEngine
from task_closed_loop.task_inputs import load_task_input_bundle
from task_closed_loop.tasks.continuity import TaskContinuityEngine
from task_closed_loop.tasks.generation_models import TaskOutcomeRecord
from task_closed_loop.tasks.generator import TaskGenerationEngine
from tests.support.task_layer_scenario_reasoner import TaskLayerScenarioReasoner


def task_dict(task):
    return {
        "task_id": task.task_id,
        "description": task.description,
        "origin_type": task.metadata.get("origin_type"),
        "expected_result": task.expected_reality_result,
        "reality_basis_refs": task.metadata.get("reality_basis_refs", []),
        "parent_task_ids": task.metadata.get("parent_task_ids", []),
        "parent_outcome_ids": task.metadata.get("parent_outcome_ids", []),
        "identity_anchor_refs": task.metadata.get("identity_anchor_refs", []),
        "observation_state_domain": task.metadata.get("observation_state_domain"),
        "observation_capability_ids": task.metadata.get("observation_capability_ids", []),
    }


def load_simulated_outcome(path: Path, parent_task_id: str):
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return TaskOutcomeRecord(
        outcome_id=f"simulated:{path.parent.name}:outcome-1",
        task_id=parent_task_id,
        outcome_status=str(raw.get("outcome_status") or "completed"),
        result_summary=str(raw.get("result_summary") or "Simulated observation outcome."),
        evidence_refs=tuple(str(x) for x in raw.get("evidence_refs") or []),
        payload=raw.get("payload"),
        subject_refs=tuple(str(x) for x in raw.get("subject_refs") or []),
    )


def load_simulated_outcomes(path: Path, observation_tasks):
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    parent_by_domain = {
        str(task.metadata.get("observation_state_domain") or ""): task
        for task in observation_tasks
    }
    outcomes = []
    for index, item in enumerate(raw.get("outcomes") or [], start=1):
        state_domain = str(item.get("state_domain") or "").strip()
        parent = parent_by_domain.get(state_domain)
        if parent is None:
            raise RuntimeError(
                f"{path.parent.name}: no observation parent for state_domain={state_domain!r}"
            )
        outcomes.append(
            TaskOutcomeRecord(
                outcome_id=f"simulated:{path.parent.name}:outcome-{index}",
                task_id=parent.task_id,
                outcome_status=str(item.get("outcome_status") or "completed"),
                result_summary=str(item.get("result_summary") or "Simulated observation outcome."),
                evidence_refs=tuple(str(x) for x in item.get("evidence_refs") or []),
                payload=item.get("payload"),
                subject_refs=tuple(str(x) for x in item.get("subject_refs") or []),
            )
        )
    return outcomes


async def run_one(scenario_dir: Path):
    bundle = load_task_input_bundle(
        scenario_dir / "resources.yml",
        scenario_dir / "capabilities.yml",
    )
    reasoner = TaskLayerScenarioReasoner()
    runtime = RuntimeOrchestrator(
        reality_engine=RealityEngine(reasoner),
        task_continuity=TaskContinuityEngine(reasoner),
        task_generation=TaskGenerationEngine(
            task_reasoner=reasoner,
            audit_reasoner=reasoner,
            coverage_expansion_min_tasks=0,
        ),
    )
    first = await runtime.run_cycle(
        RuntimeCycleInput(
            resources=list(bundle.resources),
            capabilities=list(bundle.capabilities),
        )
    )
    output = {
        "scenario": scenario_dir.name,
        "cycle_1": {
            "discovery_count": len(first.discoveries),
            "task_count": len(first.new_tasks),
            "observation_task_count": len(first.observation_tasks),
            "tasks": [task_dict(task) for task in first.new_tasks],
        },
    }

    single_outcome_path = scenario_dir / "simulated_outcome.yml"
    multi_outcomes_path = scenario_dir / "simulated_outcomes.yml"
    outcomes = []
    if single_outcome_path.exists():
        if not first.observation_tasks:
            raise RuntimeError(f"{scenario_dir.name}: simulated_outcome requires an observation parent task")
        parent = first.observation_tasks[0]
        outcomes = [load_simulated_outcome(single_outcome_path, parent.task_id)]
    elif multi_outcomes_path.exists():
        if not first.observation_tasks:
            raise RuntimeError(f"{scenario_dir.name}: simulated_outcomes requires observation parent tasks")
        outcomes = load_simulated_outcomes(multi_outcomes_path, first.observation_tasks)

    if outcomes:
        second = await runtime.run_cycle(
            RuntimeCycleInput(
                resources=list(bundle.resources),
                capabilities=list(bundle.capabilities),
                existing_tasks=list(first.observation_tasks),
                task_outcomes=outcomes,
            )
        )
        output["cycle_2_after_outcome"] = {
            "discovery_count": len(second.discoveries),
            "task_count": len(second.new_tasks),
            "observation_task_count": len(second.observation_tasks),
            "proliferation_seed_count": len(second.task_generation.trace.proliferation_seeds),
            "consumed_outcome_ids": list(second.task_generation.trace.consumed_outcome_ids),
            "tasks": [task_dict(task) for task in second.new_tasks],
        }
    return output


async def main_async(selected: str | None, output_path: Path | None):
    root = ROOT / "config" / "task_layer_scenarios"
    dirs = sorted(p for p in root.iterdir() if p.is_dir())
    if selected:
        dirs = [p for p in dirs if p.name == selected]
        if not dirs:
            raise SystemExit(f"Unknown scenario: {selected}")
    results = [await run_one(path) for path in dirs]
    text = json.dumps(results, ensure_ascii=False, indent=2)
    print(text)
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario")
    parser.add_argument("--output")
    args = parser.parse_args()
    asyncio.run(main_async(args.scenario, Path(args.output) if args.output else None))


if __name__ == "__main__":
    main()
