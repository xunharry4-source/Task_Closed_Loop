from __future__ import annotations

import asyncio
from pathlib import Path

from task_closed_loop.app.orchestrator import (
    RuntimeCycleInput,
    RuntimeOrchestrator,
)
from task_closed_loop.config import (
    load_project_config,
)
from task_closed_loop.integration.provider_factory import (
    build_provider_registry,
)
from task_closed_loop.llm import build_llm
from task_closed_loop.reality.builder import RealityEngine
from task_closed_loop.tasks.continuity import (
    TaskContinuityEngine,
)
from task_closed_loop.tasks.generator import (
    TaskGenerationEngine,
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


async def _run(
    *,
    use_test_resources: bool,
) -> None:
    root = project_root()
    config = load_project_config(root)

    if use_test_resources:
        providers = config.setdefault(
            "providers",
            {},
        )
        test_provider = providers.setdefault(
            "test_config",
            {},
        )
        test_provider["enabled"] = True

    llm = build_llm(
        config,
        root,
    )

    registry = build_provider_registry(
        config,
        require_provider=True,
    )

    validate = getattr(
        llm,
        "validate_connection",
        None,
    )
    if validate is not None:
        await validate()

    runtime = RuntimeOrchestrator(
        registry=registry,
        reality_engine=RealityEngine(llm),
        task_continuity=TaskContinuityEngine(
            llm
        ),
        task_generation=TaskGenerationEngine(
            llm
        ),
    )

    result = await runtime.run_cycle(
        RuntimeCycleInput()
    )

    print(
        "Current Reality:",
        result.reality.current_facts,
    )
    print(
        "New Tasks:",
        [
            task.description
            for task in result.new_tasks
        ],
    )


async def main() -> None:
    """Formal runtime: MCP / real Providers only."""
    await _run(
        use_test_resources=False,
    )


async def test_main() -> None:
    """
    Developer semantic test runtime.

    Reads:
        config/test_resources.yml
        config/test_capabilities.yml

    Uses the configured real Gemini / Ollama.
    """
    await _run(
        use_test_resources=True,
    )
