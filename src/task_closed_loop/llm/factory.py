from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from task_closed_loop.llm.gemini import (
    GeminiConfigurationError,
    GeminiLLM,
)
from task_closed_loop.llm.ollama import OllamaLLM
from task_closed_loop.llm.lmstudio import LMStudioLLM


class LLMNotConfiguredError(RuntimeError):
    pass


SUPPORTED_ADAPTERS = (
    "gemini",
    "ollama",
    "lmstudio",
)


def build_llm(
    config: dict[str, Any],
    project_root: str | Path,
):
    llm_cfg = config.get("llm") or {}

    adapter = str(
        llm_cfg.get("adapter") or ""
    ).strip().lower()
    model = str(
        llm_cfg.get("model") or ""
    ).strip()

    if not adapter:
        raise LLMNotConfiguredError(
            "LLM 未配置：请设置 LLM_ADAPTER。"
            " 当前支持：gemini、ollama、lmstudio。"
        )

    if adapter not in SUPPORTED_ADAPTERS:
        raise LLMNotConfiguredError(
            f"不支持的 LLM_ADAPTER：{adapter}。"
            " 当前支持：gemini、ollama、lmstudio。"
        )

    if not model:
        raise LLMNotConfiguredError(
            "LLM 未配置：请设置 LLM_MODEL。"
        )

    prompt_manifest = str(
        llm_cfg.get(
            "prompt_manifest",
            "src/task_closed_loop/prompts/manifest.yml",
        )
    )
    roles = dict(
        llm_cfg.get("roles") or {}
    )

    if adapter == "gemini":
        if not (
            os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
        ):
            raise GeminiConfigurationError(
                "Gemini API Key 未配置。"
                "请设置 GEMINI_API_KEY "
                "或 GOOGLE_API_KEY。"
            )

        return GeminiLLM(
            project_root=project_root,
            model=model,
            prompt_manifest=prompt_manifest,
            roles=roles,
        )

    if adapter == "lmstudio":
        lmstudio_cfg = (
            llm_cfg.get("lmstudio") or {}
        )

        return LMStudioLLM(
            project_root=project_root,
            model=model,
            base_url=str(
                lmstudio_cfg.get(
                    "base_url"
                )
                or "http://127.0.0.1:1234/v1"
            ),
            timeout_seconds=float(
                lmstudio_cfg.get(
                    "timeout_seconds",
                    120,
                )
            ),
            temperature=float(
                llm_cfg.get(
                    "temperature",
                    0.0,
                )
            ),
            max_tokens=(
                int(
                    lmstudio_cfg[
                        "max_tokens"
                    ]
                )
                if lmstudio_cfg.get(
                    "max_tokens"
                )
                not in (
                    None,
                    "",
                )
                else None
            ),
            api_key=(
                str(
                    lmstudio_cfg.get(
                        "api_key"
                    )
                    or ""
                ).strip()
                or None
            ),
            prompt_manifest=prompt_manifest,
            roles=roles,
        )

    ollama_cfg = (
        llm_cfg.get("ollama") or {}
    )

    return OllamaLLM(
        project_root=project_root,
        model=model,
        base_url=str(
            ollama_cfg.get("base_url")
            or "http://127.0.0.1:11434"
        ),
        timeout_seconds=float(
            ollama_cfg.get(
                "timeout_seconds",
                120,
            )
        ),
        temperature=float(
            llm_cfg.get(
                "temperature",
                0.0,
            )
        ),
        keep_alive=str(
            ollama_cfg.get(
                "keep_alive",
                "5m",
            )
        ),
        think=bool(
            ollama_cfg.get(
                "think",
                False,
            )
        ),
        prompt_manifest=prompt_manifest,
        roles=roles,
    )
