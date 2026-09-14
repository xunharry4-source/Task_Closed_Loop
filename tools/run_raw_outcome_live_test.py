from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from task_closed_loop.app.orchestrator import RuntimeCycleInput, RuntimeOrchestrator
from task_closed_loop.config.loader import load_project_config
from task_closed_loop.llm.factory import build_llm
from task_closed_loop.reality.builder import RealityEngine
from task_closed_loop.task_inputs import load_task_input_bundle
from task_closed_loop.tasks.continuity import TaskContinuityEngine
from task_closed_loop.tasks.generator import TaskGenerationEngine
from tests.support.task_layer_scenario_reasoner import TaskLayerScenarioReasoner
from tools.run_task_layer_scenarios import load_simulated_outcomes, task_dict


SCENARIO = ROOT / "config" / "task_layer_scenarios" / "08_raw_observation_outcomes"


class HybridRawOutcomeReasoner(TaskLayerScenarioReasoner):
    """Use a real configured LLM only for Raw Outcome -> descendant discovery.

    Reality, continuity, materialization and audits remain deterministic so this tool
    isolates the exact product question: can the selected model discover useful child
    TaskSeeds from raw observed content without pre-authored actionable_items?
    """

    def __init__(self, live_llm):
        self.live_llm = live_llm

    async def discover_task_proliferation_seeds(self, **kwargs):
        return await self.live_llm.discover_task_proliferation_seeds(**kwargs)


async def main_async(adapter: str | None, model: str | None, output: Path | None):
    bundle = load_task_input_bundle(
        SCENARIO / "resources.yml",
        SCENARIO / "capabilities.yml",
    )
    deterministic = TaskLayerScenarioReasoner()
    first_runtime = RuntimeOrchestrator(
        reality_engine=RealityEngine(deterministic),
        task_continuity=TaskContinuityEngine(deterministic),
        task_generation=TaskGenerationEngine(
            task_reasoner=deterministic,
            audit_reasoner=deterministic,
            coverage_expansion_min_tasks=0,
        ),
    )
    first = await first_runtime.run_cycle(
        RuntimeCycleInput(
            resources=list(bundle.resources),
            capabilities=list(bundle.capabilities),
        )
    )
    if len(first.observation_tasks) != 4:
        raise RuntimeError(
            f"Expected four Observation parents, got {len(first.observation_tasks)}"
        )

    outcomes = load_simulated_outcomes(
        SCENARIO / "simulated_outcomes.yml",
        first.observation_tasks,
    )

    config = load_project_config(ROOT)
    if adapter:
        config.setdefault("llm", {}).setdefault("task", {})["adapter"] = adapter
    if model:
        config.setdefault("llm", {}).setdefault("task", {})["model"] = model
    live_llm = build_llm(config, ROOT, profile="task")
    validate = getattr(live_llm, "validate_connection", None)
    if validate is not None:
        await validate()

    hybrid = HybridRawOutcomeReasoner(live_llm)
    second_runtime = RuntimeOrchestrator(
        reality_engine=RealityEngine(deterministic),
        task_continuity=TaskContinuityEngine(deterministic),
        task_generation=TaskGenerationEngine(
            task_reasoner=hybrid,
            audit_reasoner=deterministic,
            coverage_expansion_min_tasks=0,
        ),
    )
    second = await second_runtime.run_cycle(
        RuntimeCycleInput(
            resources=list(bundle.resources),
            capabilities=list(bundle.capabilities),
            existing_tasks=list(first.observation_tasks),
            task_outcomes=outcomes,
        )
    )

    result = {
        "adapter": adapter or config.get("llm", {}).get("task", {}).get("adapter"),
        "model": model or config.get("llm", {}).get("task", {}).get("model"),
        "raw_fixture_has_actionable_items": False,
        "observation_parent_count": len(first.observation_tasks),
        "raw_outcome_count": len(outcomes),
        "proliferation_seed_count": len(second.task_generation.trace.proliferation_seeds),
        "business_task_count": len(second.new_tasks),
        "seed_validation_errors": dict(second.task_generation.trace.seed_validation_errors),
        "consumed_outcome_ids": list(second.consumed_outcome_ids),
        "payload_context": dict(second.task_generation.trace.proliferation_payload_context),
        "tasks": [task_dict(task) for task in second.new_tasks],
    }
    text = json.dumps(result, ensure_ascii=False, indent=2)
    print(text)
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--adapter",
        choices=[
            "gemini", "gemini_cli", "codex_cli", "gemma",
            "ollama", "lmstudio", "openai", "deepseek",
        ],
    )
    parser.add_argument("--model")
    parser.add_argument("--output")
    args = parser.parse_args()
    asyncio.run(main_async(args.adapter, args.model, Path(args.output) if args.output else None))


if __name__ == "__main__":
    main()
