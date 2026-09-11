from __future__ import annotations

import importlib
from typing import Any

from .registry import ProviderRegistry


class ProviderNotConfiguredError(RuntimeError):
    pass


def import_symbol(path: str):
    module_name, symbol_name = path.split(
        ":",
        1,
    )
    module = importlib.import_module(
        module_name
    )
    return getattr(
        module,
        symbol_name,
    )


def build_provider_registry(
    config: dict[str, Any],
    *,
    require_provider: bool = False,
) -> ProviderRegistry:
    registry = ProviderRegistry()

    for provider_id, provider_cfg in (
        config.get("providers", {}) or {}
    ).items():
        if not provider_cfg.get(
            "enabled",
            False,
        ):
            continue

        adapter_path = provider_cfg.get(
            "adapter"
        )
        if not adapter_path:
            raise ProviderNotConfiguredError(
                f"Provider '{provider_id}' "
                "缺少 adapter 配置。"
            )

        adapter_cls = import_symbol(
            str(adapter_path)
        )

        options = dict(
            provider_cfg.get("options")
            or {}
        )

        try:
            provider = adapter_cls(
                **options
            )
        except (TypeError, ValueError) as exc:
            raise ProviderNotConfiguredError(
                f"Provider '{provider_id}' "
                f"配置错误：{exc}"
            ) from exc

        if (
            provider.manifest.provider_id
            != provider_id
        ):
            raise ValueError(
                "provider id mismatch: "
                f"config={provider_id}, "
                f"manifest="
                f"{provider.manifest.provider_id}"
            )

        registry.register(provider)

    # MCP is the preferred external-system integration path.
    # Every enabled MCP server becomes one generic Provider.
    from task_closed_loop.adapters.mcp_provider import (
        MCPConfigurationError,
        MCPProvider,
    )

    for server_id, server_cfg in (
        (config.get("mcp", {}) or {})
        .get("servers", {})
        .items()
    ):
        if not isinstance(server_cfg, dict):
            raise ProviderNotConfiguredError(
                f"MCP Server '{server_id}' 配置必须是 mapping。"
            )

        if not server_cfg.get(
            "enabled",
            False,
        ):
            continue

        try:
            provider = MCPProvider(
                server_id=str(server_id),
                transport=str(
                    server_cfg.get(
                        "transport",
                        "",
                    )
                ),
                url=server_cfg.get("url"),
                command=server_cfg.get(
                    "command"
                ),
                args=list(
                    server_cfg.get("args")
                    or []
                ),
                env=dict(
                    server_cfg.get("env")
                    or {}
                ),
                resource_tools=list(
                    server_cfg.get(
                        "resource_tools"
                    )
                    or []
                ),
            )
        except (
            TypeError,
            ValueError,
            MCPConfigurationError,
        ) as exc:
            raise ProviderNotConfiguredError(
                f"MCP Server '{server_id}' 配置错误：{exc}"
            ) from exc

        registry.register(provider)

    if (
        require_provider
        and not registry.manifests()
    ):
        raise ProviderNotConfiguredError(
            "没有启用任何 Resource / Capability Provider。"
            " 正式外部系统优先在 config/mcp_servers.yml 添加 MCP Server；"
            "开发测试直接运行 test_runtime.py，数据来自 "
            "config/test_resources.yml 与 config/test_capabilities.yml。"
        )

    return registry
