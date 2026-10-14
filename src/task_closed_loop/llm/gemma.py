from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from task_closed_loop.llm.gemini import (
    GeminiConfigurationError,
    GeminiDependencyError,
    GeminiLLM,
    GeminiResponseError,
    _jsonable,
)

# Gemma 4 hosted through the Gemini API uses the same google-genai client and
# credentials, but the supported request primitive is models.generate_content.
GemmaConfigurationError = GeminiConfigurationError
GemmaDependencyError = GeminiDependencyError
GemmaResponseError = GeminiResponseError


class GemmaRequestError(RuntimeError):
    pass


class GemmaLLM(GeminiLLM):
    """Hosted Gemma 4 adapter using the Gemini API generateContent surface.

    Local Gemma 4 remains supported through the existing Ollama/LM Studio
    adapters.  This adapter is specifically for Google's hosted Gemma models.
    """

    def __init__(
        self,
        *,
        project_root,
        model: str,
        thinking_level: str = "high",
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
        **kwargs,
    ):
        level = str(thinking_level or "high").strip().lower()
        if level not in {"high", "minimal"}:
            raise GemmaConfigurationError(
                "Gemma 4 thinking_level 仅支持 high 或 minimal。"
            )
        self.thinking_level = level
        self.temperature = float(temperature)
        self.max_output_tokens = (
            int(max_output_tokens)
            if max_output_tokens not in (None, "")
            else None
        )
        super().__init__(
            project_root=project_root,
            model=model,
            **kwargs,
        )

    def _create_interaction(
        self,
        *,
        role_key: str,
        input_payload: dict[str, Any],
        schema: dict[str, Any],
    ):
        prompt = self._role_prompt(role_key)
        input_text = (
            prompt
            + "\n\n【本轮输入】\n"
            + __import__("json").dumps(
                _jsonable(input_payload),
                ensure_ascii=False,
                indent=2,
            )
            + "\n\n根据本轮输入完成上述职责。"
            + "只返回满足 JSON Schema 的 JSON。"
        )

        if self.prompt_cache is not None:
            self.prompt_cache.record(
                provider="gemma",
                model=self.model,
                role_key=role_key,
                prompt=input_text,
                metadata={"transport": "genai_generate_content"},
            )

        config: dict[str, Any] = {
            "response_mime_type": "application/json",
            "response_json_schema": schema,
            "temperature": self.temperature,
            "thinking_config": {
                "thinking_level": self.thinking_level,
            },
        }
        if self.max_output_tokens is not None:
            config["max_output_tokens"] = self.max_output_tokens

        self.debugger.request(
            adapter="gemma",
            model=self.model,
            role=role_key,
            prompt=input_text,
            response_contract=schema,
        )

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=input_text,
                config=config,
            )
        except Exception as exc:
            raise GemmaRequestError(
                f"Gemma 4 generate_content 调用失败：{exc}"
            ) from exc

        text = getattr(response, "text", None)
        if not isinstance(text, str):
            raise GemmaResponseError(
                "Gemma 4 generate_content 响应缺少 text。"
            )
        return SimpleNamespace(output_text=text)
