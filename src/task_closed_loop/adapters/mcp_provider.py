from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from task_closed_loop.integration.models import (
    CapabilityDescriptor,
    ExecutionObservation,
    ProviderManifest,
    ResourceDescriptor,
    ResourceSnapshot,
)


class MCPDependencyError(RuntimeError):
    pass


class MCPConfigurationError(ValueError):
    pass


class MCPProviderError(RuntimeError):
    pass


def _stringify_content(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, dict):
        return {
            str(key): _stringify_content(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [
            _stringify_content(item)
            for item in value
        ]

    if hasattr(value, "model_dump"):
        return _stringify_content(
            value.model_dump()
        )

    if hasattr(value, "__dict__"):
        return _stringify_content(
            vars(value)
        )

    return str(value)


class MCPProvider:
    """
    Generic MCP -> Task Closed-Loop adapter.

    Native MCP resources become Resources.
    MCP tools become Capabilities.
    Configured read-only resource_tools become Resources.
    """

    def __init__(
        self,
        *,
        server_id: str,
        transport: str,
        url: str | None = None,
        command: str | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        resource_tools: list[dict[str, Any]] | None = None,
        client_factory: Callable[[], Any] | None = None,
    ):
        server_id = str(server_id or "").strip()
        if not server_id:
            raise MCPConfigurationError(
                "MCP Server 缺少 server_id。"
            )

        transport = str(
            transport or ""
        ).strip().lower()

        if transport not in {
            "streamable_http",
            "stdio",
        }:
            raise MCPConfigurationError(
                f"MCP Server '{server_id}' transport "
                "必须是 streamable_http 或 stdio。"
            )

        if (
            transport == "streamable_http"
            and not str(url or "").strip()
        ):
            raise MCPConfigurationError(
                f"MCP Server '{server_id}' 缺少 url。"
            )

        if (
            transport == "stdio"
            and not str(command or "").strip()
        ):
            raise MCPConfigurationError(
                f"MCP Server '{server_id}' 缺少 command。"
            )

        self.server_id = server_id
        self.transport = transport
        self.url = (
            str(url).strip()
            if url is not None
            else None
        )
        self.command = (
            str(command).strip()
            if command is not None
            else None
        )
        self.args = [
            str(value)
            for value in (args or [])
        ]
        self.env = {
            str(key): str(value)
            for key, value in (env or {}).items()
            if value is not None
        }
        self.resource_tools = [
            self._normalize_resource_tool(item)
            for item in (resource_tools or [])
        ]
        self._client_factory = client_factory
        self._resource_uri_by_id: dict[
            str,
            str,
        ] = {}

        self._manifest = ProviderManifest(
            provider_id=self.server_id,
            provider_type="mcp",
            resource_support=("mcp_resource",),
            capability_support=("mcp_tool",),
        )

    @property
    def manifest(self):
        return self._manifest

    def _normalize_resource_tool(
        self,
        item: Any,
    ) -> dict[str, Any]:
        if not isinstance(item, dict):
            raise MCPConfigurationError(
                f"MCP Server '{self.server_id}' "
                "resource_tools 每项必须是 mapping。"
            )

        resource_id = str(
            item.get("id") or ""
        ).strip()
        tool = str(
            item.get("tool") or ""
        ).strip()

        if not resource_id:
            raise MCPConfigurationError(
                f"MCP Server '{self.server_id}' "
                "resource_tool 缺少 id。"
            )

        if not tool:
            raise MCPConfigurationError(
                f"MCP Server '{self.server_id}' "
                f"resource_tool '{resource_id}' 缺少 tool。"
            )

        arguments = item.get(
            "arguments"
        ) or {}
        if not isinstance(arguments, dict):
            raise MCPConfigurationError(
                f"MCP resource_tool '{resource_id}' "
                "arguments 必须是 mapping。"
            )

        return {
            "id": resource_id,
            "tool": tool,
            "resource_type": str(
                item.get(
                    "resource_type",
                    "mcp_tool_result",
                )
            ),
            "arguments": arguments,
            "description": str(
                item.get("description") or ""
            ),
        }

    def _build_client(self):
        if self._client_factory is not None:
            return self._client_factory()

        try:
            from mcp import (
                Client,
                StdioServerParameters,
            )
            from mcp.client.stdio import (
                stdio_client,
            )
        except ImportError as exc:
            raise MCPDependencyError(
                "当前 Python 环境未安装 MCP SDK。"
                '请运行：pip install "mcp>=2,<3"'
            ) from exc

        if self.transport == "streamable_http":
            return Client(self.url)

        params = StdioServerParameters(
            command=self.command,
            args=self.args,
            env=self.env or None,
        )
        return Client(
            stdio_client(params)
        )

    async def _with_client(
        self,
        callback,
    ):
        client_context = self._build_client()

        try:
            async with client_context as client:
                return await callback(client)
        except (
            MCPDependencyError,
            MCPConfigurationError,
        ):
            raise
        except Exception as exc:
            raise MCPProviderError(
                f"MCP Server '{self.server_id}' 调用失败：{exc}"
            ) from exc

    async def discover_resources(self):
        async def run(client):
            out = []

            server_capabilities = getattr(
                client,
                "server_capabilities",
                None,
            )
            resource_capability = getattr(
                server_capabilities,
                "resources",
                None,
            )

            if resource_capability is None:
                resources = []
            else:
                result = await client.list_resources()
                resources = getattr(
                    result,
                    "resources",
                    [],
                )

            for item in resources:
                uri = str(
                    getattr(item, "uri", "")
                )
                if not uri:
                    continue

                resource_id = (
                    "resource:"
                    + uri
                )
                self._resource_uri_by_id[
                    resource_id
                ] = uri

                out.append(
                    ResourceDescriptor(
                        resource_id=resource_id,
                        provider_id=self.server_id,
                        resource_type=(
                            str(
                                getattr(
                                    item,
                                    "mime_type",
                                    None,
                                )
                                or "mcp_resource"
                            )
                        ),
                        source_identity=uri,
                    )
                )

            for item in self.resource_tools:
                out.append(
                    ResourceDescriptor(
                        resource_id=(
                            "tool_resource:"
                            + item["id"]
                        ),
                        provider_id=self.server_id,
                        resource_type=(
                            item["resource_type"]
                        ),
                        source_identity=(
                            "mcp-tool://"
                            + self.server_id
                            + "/"
                            + item["tool"]
                        ),
                    )
                )

            return out

        return await self._with_client(run)

    async def read_resource(
        self,
        ref,
    ):
        if ref.resource_id.startswith(
            "tool_resource:"
        ):
            logical_id = ref.resource_id.split(
                ":",
                1,
            )[1]
            config = next(
                (
                    item
                    for item in self.resource_tools
                    if item["id"] == logical_id
                ),
                None,
            )
            if config is None:
                raise MCPProviderError(
                    f"未知 MCP resource_tool：{logical_id}"
                )

            async def run(client):
                result = await client.call_tool(
                    config["tool"],
                    config["arguments"],
                )

                is_error = bool(
                    getattr(
                        result,
                        "is_error",
                        False,
                    )
                )
                if is_error:
                    raise MCPProviderError(
                        f"MCP resource_tool "
                        f"'{config['tool']}' 返回错误。"
                    )

                structured = getattr(
                    result,
                    "structured_content",
                    None,
                )
                content = getattr(
                    result,
                    "content",
                    None,
                )

                payload = (
                    _stringify_content(
                        structured
                    )
                    if structured is not None
                    else _stringify_content(
                        content
                    )
                )

                return ResourceSnapshot(
                    resource_id=ref.resource_id,
                    provider_id=self.server_id,
                    source_identity=(
                        "mcp-tool://"
                        + self.server_id
                        + "/"
                        + config["tool"]
                    ),
                    resource_type=(
                        config["resource_type"]
                    ),
                    payload={
                        "data": payload,
                        "description": (
                            config["description"]
                        ),
                    },
                )

            return await self._with_client(run)

        uri = self._resource_uri_by_id.get(
            ref.resource_id
        )
        if not uri:
            if ref.resource_id.startswith(
                "resource:"
            ):
                uri = ref.resource_id[
                    len("resource:") :
                ]

        if not uri:
            raise MCPProviderError(
                f"未知 MCP Resource：{ref.resource_id}"
            )

        async def run(client):
            result = await client.read_resource(
                uri
            )
            contents = getattr(
                result,
                "contents",
                [],
            )

            return ResourceSnapshot(
                resource_id=ref.resource_id,
                provider_id=self.server_id,
                source_identity=uri,
                resource_type="mcp_resource",
                payload={
                    "uri": uri,
                    "contents": _stringify_content(
                        contents
                    ),
                },
            )

        return await self._with_client(run)

    async def discover_capabilities(self):
        async def run(client):
            server_capabilities = getattr(
                client,
                "server_capabilities",
                None,
            )
            tool_capability = getattr(
                server_capabilities,
                "tools",
                None,
            )

            if tool_capability is None:
                return []

            result = await client.list_tools()
            tools = getattr(
                result,
                "tools",
                [],
            )

            out = []

            for tool in tools:
                name = str(
                    getattr(
                        tool,
                        "name",
                        "",
                    )
                ).strip()
                if not name:
                    continue

                description = (
                    getattr(
                        tool,
                        "description",
                        None,
                    )
                    or getattr(
                        tool,
                        "title",
                        None,
                    )
                    or name
                )

                schema = getattr(
                    tool,
                    "input_schema",
                    None,
                )
                if schema is None:
                    schema = getattr(
                        tool,
                        "inputSchema",
                        None,
                    )
                if not isinstance(schema, dict):
                    if hasattr(
                        schema,
                        "model_dump",
                    ):
                        schema = (
                            schema.model_dump()
                        )
                    else:
                        schema = {}

                out.append(
                    CapabilityDescriptor(
                        capability_id=(
                            "mcp."
                            + self.server_id
                            + "."
                            + name
                        ),
                        provider_id=self.server_id,
                        action_type=name,
                        principal=(
                            "mcp:"
                            + self.server_id
                        ),
                        security_domain=(
                            "mcp:"
                            + self.server_id
                        ),
                        target_scope={
                            "mcp_server": (
                                self.server_id
                            ),
                            "tool": name,
                        },
                        permissions=("execute",),
                        availability="available",
                        description=str(
                            description
                        ),
                        input_schema=dict(
                            schema
                        ),
                    )
                )

            return out

        return await self._with_client(run)

    async def execute(
        self,
        request,
    ):
        tool_name = str(
            request.action_type or ""
        ).strip()

        if not tool_name:
            raise MCPProviderError(
                "MCP ExecutionRequest 缺少 action_type/tool name。"
            )

        async def run(client):
            result = await client.call_tool(
                tool_name,
                dict(request.payload),
            )

            is_error = bool(
                getattr(
                    result,
                    "is_error",
                    False,
                )
            )
            if is_error:
                raise MCPProviderError(
                    f"MCP Tool '{tool_name}' 返回错误。"
                )

            structured = getattr(
                result,
                "structured_content",
                None,
            )
            content = getattr(
                result,
                "content",
                None,
            )

            raw_result = (
                _stringify_content(
                    structured
                )
                if structured is not None
                else _stringify_content(
                    content
                )
            )

            return ExecutionObservation(
                provider_id=self.server_id,
                attempt_id=(
                    request.attempt_id
                ),
                target_at_execution=dict(
                    request.target
                ),
                effect_scope={
                    "action_type": tool_name,
                    "mcp_server": (
                        self.server_id
                    ),
                },
                commit_knowledge=(
                    "confirmed_committed"
                ),
                evidence_refs=(
                    "mcp:"
                    + self.server_id
                    + ":"
                    + tool_name
                    + ":"
                    + request.attempt_id,
                ),
                raw_result=raw_result,
            )

        return await self._with_client(run)
