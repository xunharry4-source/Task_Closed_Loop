from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from task_closed_loop.llm.debug import LLMDebugPrinter
from task_closed_loop.llm.prompt_cache import PromptRequestCache
from task_closed_loop.llm.gemini import (
    GeminiLLM,
    _jsonable,
)
from task_closed_loop.llm.prompt_registry import (
    PromptRegistry,
)


class LMStudioConfigurationError(RuntimeError):
    pass


class LMStudioConnectionError(RuntimeError):
    pass


class LMStudioResponseError(RuntimeError):
    pass


class LMStudioTransport:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        api_key: str | None = None,
    ):
        value = str(base_url or "").strip()

        if not value:
            raise LMStudioConfigurationError(
                "LM Studio base_url 为空。"
            )

        self.base_url = value.rstrip("/")
        self.timeout_seconds = float(
            timeout_seconds
        )
        self.api_key = (
            str(api_key).strip()
            if api_key
            else None
        )

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = (
            self.base_url
            + "/"
            + path.lstrip("/")
        )

        headers = {
            "Content-Type": "application/json",
        }

        if self.api_key:
            headers["Authorization"] = (
                "Bearer " + self.api_key
            )

        body = None
        if payload is not None:
            body = json.dumps(
                payload,
                ensure_ascii=False,
            ).encode("utf-8")

        request = Request(
            url,
            data=body,
            method=method,
            headers=headers,
        )

        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                raw = response.read().decode(
                    "utf-8",
                    errors="replace",
                )
        except HTTPError as exc:
            detail = exc.read().decode(
                "utf-8",
                errors="replace",
            )
            raise LMStudioConnectionError(
                f"LM Studio HTTP {exc.code}: "
                f"{detail}"
            ) from exc
        except URLError as exc:
            raise LMStudioConnectionError(
                "无法连接 LM Studio："
                f"{url}；{exc.reason}"
            ) from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LMStudioResponseError(
                "LM Studio 返回了非 JSON HTTP 响应。"
            ) from exc

        if not isinstance(data, dict):
            raise LMStudioResponseError(
                "LM Studio HTTP 响应根节点必须是 "
                "JSON object。"
            )

        return data

    async def get_json(
        self,
        path: str,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._request_json,
            "GET",
            path,
            None,
        )

    async def post_json(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._request_json,
            "POST",
            path,
            payload,
        )


class LMStudioLLM(GeminiLLM):
    """
    LM Studio OpenAI-compatible adapter.

    Uses:
        GET  /v1/models
        POST /v1/chat/completions

    base_url is expected to include /v1.
    """

    def __init__(
        self,
        *,
        project_root: str | Path,
        model: str,
        base_url: str = (
            "http://127.0.0.1:1234/v1"
        ),
        timeout_seconds: float = 120,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        api_key: str | None = None,
        prompt_manifest: str = (
            "src/task_closed_loop/prompts/"
            "manifest.yml"
        ),
        roles: dict[str, str] | None = None,
        transport: LMStudioTransport
        | Any
        | None = None,
        debugger: LLMDebugPrinter | None = None,
        prompt_cache: PromptRequestCache | None = None,
    ):
        model = str(model or "").strip()

        if not model:
            raise LMStudioConfigurationError(
                "model 未配置。"
            )

        self.model = model
        self.temperature = float(
            temperature
        )
        self.max_tokens = (
            int(max_tokens)
            if max_tokens is not None
            else None
        )
        self.roles = dict(
            roles or {}
        )
        self.debugger = (
            debugger
            if debugger is not None
            else LLMDebugPrinter()
        )
        self.prompt_cache = prompt_cache
        self.prompts = PromptRegistry(
            project_root,
            prompt_manifest,
        )
        self.transport = (
            transport
            if transport is not None
            else LMStudioTransport(
                base_url=base_url,
                timeout_seconds=(
                    timeout_seconds
                ),
                api_key=api_key,
            )
        )

    async def validate_connection(
        self,
    ) -> None:
        result = await self.transport.get_json(
            "/models"
        )

        data = result.get("data")

        if not isinstance(data, list):
            raise LMStudioResponseError(
                "LM Studio /v1/models 缺少 data array。"
            )

        names = {
            str(item.get("id") or "").strip()
            for item in data
            if isinstance(item, dict)
        }
        names.discard("")

        if self.model not in names:
            available = ", ".join(
                sorted(names)
            )
            suffix = (
                f" 当前可见模型：{available}"
                if available
                else " 当前没有返回可见模型。"
            )

            raise LMStudioConfigurationError(
                "LM Studio 模型未找到："
                f"{self.model}。"
                + suffix
            )

    async def _interaction_json(
        self,
        *,
        role_key: str,
        input_payload: dict[str, Any],
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = self._role_prompt(
            role_key
        )

        user_text = json.dumps(
            _jsonable(input_payload),
            ensure_ascii=False,
            indent=2,
        )

        request_payload: dict[
            str,
            Any,
        ] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": prompt,
                },
                {
                    "role": "user",
                    "content": (
                        "【本轮输入】\n"
                        + user_text
                        + "\n\n根据本轮输入完成上述职责。"
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": (
                        role_key
                        + "_response"
                    ),
                    "strict": True,
                    "schema": schema,
                },
            },
            "temperature": (
                self.temperature
            ),
            "stream": False,
        }

        if self.max_tokens is not None:
            request_payload[
                "max_tokens"
            ] = self.max_tokens

        if self.prompt_cache is not None:
            self.prompt_cache.record(
                provider="lmstudio",
                model=self.model,
                role_key=role_key,
                prompt=json.dumps(
                    {
                        "messages": request_payload[
                            "messages"
                        ],
                        "response_format": request_payload[
                            "response_format"
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                ),
                metadata={
                    "transport": "openai_compatible_chat_completions",
                    "endpoint": "/chat/completions",
                },
            )

        self.debugger.request(
            adapter="lmstudio",
            model=self.model,
            role=role_key,
            prompt={
                "messages": request_payload[
                    "messages"
                ],
            },
            response_contract=(
                request_payload[
                    "response_format"
                ]
            ),
        )

        response = (
            await self.transport.post_json(
                "/chat/completions",
                request_payload,
            )
        )

        choices = response.get(
            "choices"
        )
        if (
            not isinstance(choices, list)
            or not choices
        ):
            raise LMStudioResponseError(
                "LM Studio /v1/chat/completions "
                "缺少 choices。"
            )

        first = choices[0]
        if not isinstance(first, dict):
            raise LMStudioResponseError(
                "LM Studio choices[0] "
                "必须是 object。"
            )

        message = first.get(
            "message"
        )
        if not isinstance(
            message,
            dict,
        ):
            raise LMStudioResponseError(
                "LM Studio choices[0].message "
                "缺失。"
            )

        content = message.get(
            "content"
        )
        if not isinstance(
            content,
            str,
        ):
            raise LMStudioResponseError(
                "LM Studio message.content "
                "不是字符串。"
            )

        try:
            parsed = json.loads(
                content.strip()
            )
        except json.JSONDecodeError as exc:
            raise LMStudioResponseError(
                "LM Studio structured output "
                "不是可解析的 JSON。"
            ) from exc

        if not isinstance(
            parsed,
            dict,
        ):
            raise LMStudioResponseError(
                "LM Studio structured output "
                "根节点必须是 object。"
            )

        return parsed
