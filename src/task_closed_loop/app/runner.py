from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable

from task_closed_loop.adapters.mcp_provider import (
    MCPDependencyError,
    MCPProviderError,
)
from task_closed_loop.integration.provider_factory import (
    ProviderNotConfiguredError,
)
from task_closed_loop.llm import (
    GeminiConfigurationError,
    GeminiDependencyError,
    GeminiRequestError,
    GeminiResponseError,
    LLMNotConfiguredError,
    LMStudioConfigurationError,
    LMStudioConnectionError,
    LMStudioResponseError,
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
        LLMNotConfiguredError,
        GeminiConfigurationError,
        GeminiDependencyError,
        OllamaConfigurationError,
        OllamaConnectionError,
        LMStudioConfigurationError,
        LMStudioConnectionError,
        ProviderNotConfiguredError,
        MCPDependencyError,
    ) as exc:
        print(
            f"[CONFIG ERROR] {exc}",
            file=sys.stderr,
        )
        raise SystemExit(2)
    except (
        GeminiRequestError,
        GeminiResponseError,
        OllamaResponseError,
        LMStudioResponseError,
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
