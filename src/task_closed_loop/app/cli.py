from __future__ import annotations

import asyncio
import sys

from task_closed_loop.app.runtime import (
    main as runtime_main,
)
from task_closed_loop.integration.provider_factory import (
    ProviderNotConfiguredError,
)
from task_closed_loop.adapters.mcp_provider import (
    MCPDependencyError,
    MCPProviderError,
)
from task_closed_loop.llm import (
    GeminiConfigurationError,
    GeminiDependencyError,
    GeminiRequestError,
    GeminiResponseError,
    LLMNotConfiguredError,
    OllamaConfigurationError,
    OllamaConnectionError,
    OllamaResponseError,
)


def main() -> None:
    try:
        asyncio.run(runtime_main())
    except (
        LLMNotConfiguredError,
        GeminiConfigurationError,
        GeminiDependencyError,
        OllamaConfigurationError,
        OllamaConnectionError,
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


if __name__ == "__main__":
    main()
