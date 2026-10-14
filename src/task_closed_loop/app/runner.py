from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable

from task_closed_loop.architecture import ArchitectureContractError
from task_closed_loop.app.production_pipeline import ProductionStageError
from task_closed_loop.adapters.mcp_provider import (
    MCPDependencyError,
    MCPProviderError,
)
from task_closed_loop.capability_runtime.errors import (
    CliEngineError,
)
from task_closed_loop.capability_runtime.workspace import (
    CliProjectStructureError,
)
from task_closed_loop.integration.provider_factory import (
    ProviderNotConfiguredError,
)
from task_closed_loop.preflight.cli_preflight import (
    PreflightAnalysisError,
    PreflightSourceConfigurationError,
)
from task_closed_loop.projects.config import ProjectConfigurationError
from task_closed_loop.store.task_store import TaskStoreError
from task_closed_loop.task_inputs import (
    TaskInputConfigurationError,
)
from task_closed_loop.llm import (
    GemmaRequestError,
    GeminiConfigurationError,
    GeminiDependencyError,
    CodexCliConfigurationError,
    CodexCliRequestError,
    CodexCliResponseError,
    GeminiCliConfigurationError,
    GeminiCliRequestError,
    GeminiCliResponseError,
    GeminiRequestError,
    GeminiResponseError,
    LLMNotConfiguredError,
    LMStudioConfigurationError,
    LMStudioConnectionError,
    LMStudioResponseError,
    OpenAICompatibleConfigurationError,
    OpenAICompatibleConnectionError,
    OpenAICompatibleResponseError,
    OllamaConfigurationError,
    OllamaConnectionError,
    OllamaResponseError,
)


def run(
    runtime_factory: Callable[[], Awaitable[None]],
) -> None:
    try:
        asyncio.run(runtime_factory())
    except (
        # Stage 1-2 gates. These stop the run before Task generation on purpose:
        # without prepared reality and capability facts there is nothing to discover.
        ArchitectureContractError,
        CliProjectStructureError,
        PreflightSourceConfigurationError,
        ProductionStageError,
    ) as exc:
        print(
            f"[STAGE ERROR] {exc}",
            file=sys.stderr,
        )
        raise SystemExit(5)
    except (
        CliEngineError,
        PreflightAnalysisError,
    ) as exc:
        print(
            f"[CLI PREFLIGHT ERROR] {exc}",
            file=sys.stderr,
        )
        raise SystemExit(6)
    except TaskInputConfigurationError as exc:
        print(
            f"[TASK INPUT ERROR] {exc}",
            file=sys.stderr,
        )
        raise SystemExit(7)
    except ProjectConfigurationError as exc:
        # Project ownership is the user's statement; guessing it would mix projects.
        print(
            f"[PROJECT CONFIG ERROR] {exc}",
            file=sys.stderr,
        )
        raise SystemExit(8)
    except TaskStoreError as exc:
        print(
            f"[TASK STORE ERROR] {exc}",
            file=sys.stderr,
        )
        raise SystemExit(9)
    except (
        LLMNotConfiguredError,
        GeminiConfigurationError,
        GeminiCliConfigurationError,
        CodexCliConfigurationError,
        GeminiDependencyError,
        OllamaConfigurationError,
        OllamaConnectionError,
        LMStudioConfigurationError,
        LMStudioConnectionError,
        OpenAICompatibleConfigurationError,
        OpenAICompatibleConnectionError,
        ProviderNotConfiguredError,
        MCPDependencyError,
    ) as exc:
        print(
            f"[CONFIG ERROR] {exc}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    except (
        GemmaRequestError,
        CodexCliRequestError,
        CodexCliResponseError,
        GeminiCliRequestError,
        GeminiCliResponseError,
        GeminiRequestError,
        GeminiResponseError,
        OllamaResponseError,
        LMStudioResponseError,
        OpenAICompatibleResponseError,
    ) as exc:
        print(
            f"[LLM ERROR] {exc}",
            file=sys.stderr,
        )
        raise SystemExit(3)
    except MCPProviderError as exc:
        print(
            f"[MCP ERROR] {exc}",
            file=sys.stderr,
        )
        raise SystemExit(4)
