from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from task_closed_loop.llm.debug import LLMDebugPrinter
from task_closed_loop.model_io import (
    from_model_output_contract,
    to_model_contract,
    to_model_input,
)
from task_closed_loop.llm.ollama import OllamaLLM
from task_closed_loop.llm.prompt_registry import PromptRegistry
from task_closed_loop.llm.prompt_cache import PromptRequestCache


class OpenAICompatibleConfigurationError(RuntimeError):
    pass


class OpenAICompatibleConnectionError(RuntimeError):
    pass


class OpenAICompatibleResponseError(RuntimeError):
    pass


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {
            key: _jsonable(item)
            for key, item in asdict(value).items()
        }

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
        }

    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]

    return value


def _strip_json_fence(text: str) -> str:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    return value


class OpenAICompatibleTransport:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        api_key: str,
        extra_headers: dict[str, str] | None = None,
    ):
        base_url = str(base_url or "").strip().rstrip("/")
        if not base_url:
            raise OpenAICompatibleConfigurationError(
                "OpenAI-compatible API base_url 为空。"
            )
        self.base_url = base_url
        self.timeout_seconds = float(timeout_seconds)
        self.api_key = str(api_key or "").strip()
        # 网关要求或建议的附加头（如 OpenRouter 的 HTTP-Referer / X-Title）。
        self.extra_headers = {
            str(key): str(value)
            for key, value in (extra_headers or {}).items()
            if str(value).strip()
        }

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = self.base_url + "/" + path.lstrip("/")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.extra_headers,
        }
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
            raise OpenAICompatibleConnectionError(
                f"OpenAI-compatible API HTTP {exc.code}: {detail}"
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise OpenAICompatibleConnectionError(
                f"无法连接 OpenAI-compatible API：{url}；{exc}"
            ) from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OpenAICompatibleResponseError(
                "OpenAI-compatible API 返回了非 JSON HTTP 响应。"
            ) from exc

        if not isinstance(data, dict):
            raise OpenAICompatibleResponseError(
                "OpenAI-compatible API 响应根节点必须是 JSON object。"
            )
        return data

    async def get_json(self, path: str) -> dict[str, Any]:
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


class OpenAICompatibleLLM(OllamaLLM):
    """Chat Completions adapter for OpenAI / DeepSeek / OpenRouter 这类兼容 API。"""

    def __init__(
        self,
        *,
        project_root: str | Path,
        provider_name: str,
        model: str,
        base_url: str,
        api_key: str,
        timeout_seconds: float = 120,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        prompt_manifest: str = (
            "src/task_closed_loop/prompts/manifest.yml"
        ),
        roles: dict[str, str] | None = None,
        transport: OpenAICompatibleTransport | Any | None = None,
        prompt_cache: PromptRequestCache | None = None,
        debugger: LLMDebugPrinter | None = None,
        extra_request_fields: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ):
        provider_name = str(provider_name or "").strip().lower()
        model = str(model or "").strip()
        api_key = str(api_key or "").strip()
        if not provider_name:
            raise OpenAICompatibleConfigurationError(
                "OpenAI-compatible provider_name 为空。"
            )
        if not model:
            raise OpenAICompatibleConfigurationError(
                "OpenAI-compatible model 未配置。"
            )
        if not api_key:
            raise OpenAICompatibleConfigurationError(
                f"{provider_name} API Key 未配置。"
            )

        self.provider_name = provider_name
        self.prompt_cache = prompt_cache
        self.debugger = (
            debugger
            if debugger is not None
            else LLMDebugPrinter()
        )
        self.api_key = api_key
        self.max_tokens = (
            int(max_tokens)
            if max_tokens is not None
            else None
        )
        self.prompts = PromptRegistry(project_root, prompt_manifest)
        self.roles = dict(roles or {})
        self.model = model
        self.temperature = float(temperature)
        self.extra_request_fields = dict(extra_request_fields or {})
        protected = {"model", "messages", "response_format", "stream"}
        overlap = protected & set(self.extra_request_fields)
        if overlap:
            raise OpenAICompatibleConfigurationError(
                "extra_request_fields 不得覆盖核心请求字段："
                + ", ".join(sorted(overlap))
            )
        self.transport = transport or OpenAICompatibleTransport(
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            api_key=api_key,
            extra_headers=extra_headers,
        )


    async def validate_connection(self) -> None:
        result = await self.transport.get_json("/models")
        data = result.get("data")
        if not isinstance(data, list):
            raise OpenAICompatibleResponseError(
                f"{self.provider_name} /models 缺少 data array。"
            )

        models = {
            str(item.get("id") or "").strip()
            for item in data
            if isinstance(item, dict)
        }
        models.discard("")
        if self.model not in models:
            available = ", ".join(sorted(models))
            suffix = (
                f" 当前可用模型：{available}"
                if available
                else " 当前 API 没有返回可用模型。"
            )
            raise OpenAICompatibleConfigurationError(
                f"{self.provider_name} 模型未找到：{self.model}。"
                + suffix
            )

    async def _chat_json(
        self,
        *,
        role_key: str,
        input_payload: dict[str, Any],
        contract: dict[str, Any],
    ) -> dict[str, Any]:
        # The model works with readable names; domain parsing keeps internal ones.
        input_payload = to_model_input(input_payload)
        contract = to_model_contract(contract)
        built = self._build_prompt(role_key, input_payload)
        system_prompt = built.text
        user_payload: dict[str, Any] = {}
        if built.include_input:
            user_payload["input"] = _jsonable(input_payload)
        user_payload["response_contract"] = contract
        if self.prompt_cache is not None:
            self.prompt_cache.record(
                provider=self.provider_name,
                model=self.model,
                role_key=role_key,
                prompt=(
                    system_prompt
                    + "\n\n只返回一个 JSON object。"
                    + " 字段结构遵循用户提供的 response_contract。"
                    + "\n\n【本轮输入】\n"
                    + json.dumps(
                        user_payload,
                        ensure_ascii=False,
                        indent=2,
                    )
                ),
                metadata={
                    "transport": "openai_compatible_chat_completions",
                    "endpoint": "/chat/completions",
                    "contract_keys": list(contract.keys()),
                },
            )
        request_payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        system_prompt
                        + "\n\n只返回一个 JSON object。"
                        + " 字段结构遵循用户提供的 response_contract。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        user_payload,
                        ensure_ascii=False,
                        indent=2,
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": self.temperature,
            "stream": False,
        }
        if self.max_tokens is not None:
            request_payload["max_tokens"] = self.max_tokens
        request_payload.update(self.extra_request_fields)

        self.debugger.request(
            adapter=self.provider_name,
            model=self.model,
            role=role_key,
            prompt={
                "messages": request_payload[
                    "messages"
                ],
            },
            response_contract=contract,
        )

        response = await self.transport.post_json(
            "/chat/completions",
            request_payload,
        )
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise OpenAICompatibleResponseError(
                f"{self.provider_name} chat/completions 缺少 choices。"
            )
        first = choices[0]
        if not isinstance(first, dict):
            raise OpenAICompatibleResponseError(
                "chat/completions choices[0] 必须是 object。"
            )
        message = first.get("message")
        if not isinstance(message, dict):
            raise OpenAICompatibleResponseError(
                "chat/completions choices[0].message 缺失。"
            )
        content = message.get("content")
        if not isinstance(content, str):
            raise OpenAICompatibleResponseError(
                "chat/completions message.content 不是字符串。"
            )
        try:
            parsed = json.loads(_strip_json_fence(content))
        except json.JSONDecodeError as exc:
            raise OpenAICompatibleResponseError(
                "OpenAI-compatible LLM 没有返回可解析的 JSON object。"
            ) from exc
        if self.prompt_cache is not None:
            self.prompt_cache.record_response(
                provider=self.provider_name,
                model=self.model,
                role_key=role_key,
                response=content,
            )

        if not isinstance(parsed, dict):
            raise OpenAICompatibleResponseError(
                "OpenAI-compatible LLM JSON 根节点必须是 object。"
            )
        return from_model_output_contract(parsed, contract)
