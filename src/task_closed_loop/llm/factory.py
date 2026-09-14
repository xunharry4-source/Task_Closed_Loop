from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from task_closed_loop.llm.debug import (
    LLMDebugPrinter,
)
from task_closed_loop.llm.gemini import (
    GeminiConfigurationError,
    GeminiLLM,
)
from task_closed_loop.llm.codex_cli import (
    CodexCliLLM,
)
from task_closed_loop.llm.gemini_cli import (
    GeminiCliLLM,
)
from task_closed_loop.llm.gemma import (
    GemmaConfigurationError,
    GemmaLLM,
)
from task_closed_loop.llm.lmstudio import (
    LMStudioLLM,
)
from task_closed_loop.llm.openai_compatible import (
    OpenAICompatibleConfigurationError,
    OpenAICompatibleLLM,
)
from task_closed_loop.llm.prompt_cache import (
    build_prompt_cache,
)
from task_closed_loop.diagnostics.logging import (
    current_flow_id,
)
from task_closed_loop.llm.ollama import (
    OllamaLLM,
)


class LLMNotConfiguredError(RuntimeError):
    pass


SUPPORTED_ADAPTERS = (
    "gemini",
    "gemini_cli",
    "codex_cli",
    "gemma",
    "ollama",
    "lmstudio",
    "openai",
    "deepseek",
)

SUPPORTED_PROFILES = (
    "task",
    "audit",
)


def _profile_config(
    config: dict[str, Any],
    profile: str,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
]:
    if profile not in SUPPORTED_PROFILES:
        raise LLMNotConfiguredError(
            "未知 LLM profile："
            f"{profile}。"
        )

    llm_cfg = config.get("llm") or {}
    profile_cfg = (
        llm_cfg.get(profile) or {}
    )

    return llm_cfg, profile_cfg


def build_llm(
    config: dict[str, Any],
    project_root: str | Path,
    *,
    profile: str = "task",
):
    llm_cfg, profile_cfg = (
        _profile_config(
            config,
            profile,
        )
    )

    adapter = str(
        profile_cfg.get("adapter")
        or ""
    ).strip().lower()

    model = str(
        profile_cfg.get("model")
        or ""
    ).strip()

    profile_upper = profile.upper()

    if not adapter:
        raise LLMNotConfiguredError(
            f"{profile_upper} LLM 未配置："
            f"请设置 {profile_upper}_LLM_ADAPTER。"
            " 当前支持："
            "gemini、gemini_cli、codex_cli、gemma、ollama、lmstudio、openai、deepseek。"
        )

    if adapter not in SUPPORTED_ADAPTERS:
        raise LLMNotConfiguredError(
            f"不支持的 {profile_upper}_LLM_ADAPTER："
            f"{adapter}。"
            " 当前支持："
            "gemini、gemini_cli、codex_cli、gemma、ollama、lmstudio、openai、deepseek。"
        )

    # The local CLI picks its own default model when none is configured.
    if not model and adapter not in {"gemini_cli", "codex_cli"}:
        raise LLMNotConfiguredError(
            f"{profile_upper} LLM 未配置："
            f"请设置 {profile_upper}_LLM_MODEL。"
        )

    prompt_manifest = str(
        llm_cfg.get(
            "prompt_manifest",
            "src/task_closed_loop/"
            "prompts/manifest.yml",
        )
    )

    all_roles = dict(
        llm_cfg.get("roles") or {}
    )
    profile_roles = dict(
        profile_cfg.get("roles") or {}
    )
    roles = {
        **all_roles,
        **profile_roles,
    }

    temperature = float(
        profile_cfg.get(
            "temperature",
            0.0,
        )
    )

    debug_cfg = config.get(
        "debug"
    ) or {}
    debugger = LLMDebugPrinter(
        enabled=bool(
            debug_cfg.get(
                "enabled",
                False,
            )
        ),
        scope=profile,
    )

    debugger.model_selected(
        adapter=adapter,
        model=model,
    )

    prompt_cache = build_prompt_cache(
        config,
        project_root,
        flow_id=current_flow_id(),
    )

    if adapter == "codex_cli":
        # Stage 3/4/6/7 through the locally installed codex binary. `codex exec`
        # enforces the response shape with --output-schema and writes the final
        # message with --output-last-message, so no envelope has to be parsed.
        base = llm_cfg.get("codex_cli") or {}
        override = profile_cfg.get("codex_cli") or {}
        cli_cfg = {**base, **override}
        return CodexCliLLM(
            project_root=project_root,
            model=model,
            command=str(cli_cfg.get("command") or "codex"),
            sandbox=str(cli_cfg.get("sandbox") or "read-only"),
            timeout_seconds=int(cli_cfg.get("timeout_seconds") or 600),
            max_retries=int(cli_cfg.get("max_retries") or 2),
            ignore_rules=cli_cfg.get("ignore_rules", True),
            ignore_user_config=cli_cfg.get("ignore_user_config", False),
            prompt_manifest=prompt_manifest,
            roles=roles,
            debugger=debugger,
            prompt_cache=prompt_cache,
        )

    if adapter == "gemini_cli":
        # Stage 3/4/6/7 through the locally installed gemini binary. No hosted API
        # key is required: the CLI uses its own signed-in credentials and quota.
        base = llm_cfg.get("gemini_cli") or {}
        override = profile_cfg.get("gemini_cli") or {}
        cli_cfg = {**base, **override}
        return GeminiCliLLM(
            project_root=project_root,
            model=model,
            command=str(cli_cfg.get("command") or "gemini"),
            approval_mode=str(cli_cfg.get("approval_mode") or "default"),
            timeout_seconds=int(cli_cfg.get("timeout_seconds") or 300),
            max_retries=int(cli_cfg.get("max_retries") or 2),
            prompt_manifest=prompt_manifest,
            roles=roles,
            debugger=debugger,
            prompt_cache=prompt_cache,
        )

    if adapter == "gemma":
        if not (
            os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
        ):
            raise GemmaConfigurationError(
                "Gemma 4 hosted API Key 未配置。"
                "请设置 GEMINI_API_KEY 或 GOOGLE_API_KEY。"
            )
        base = llm_cfg.get("gemma") or {}
        override = profile_cfg.get("gemma") or {}
        gemma_cfg = {**base, **override}
        return GemmaLLM(
            project_root=project_root,
            model=model,
            temperature=temperature,
            thinking_level=str(
                gemma_cfg.get("thinking_level") or "high"
            ),
            max_output_tokens=(
                int(gemma_cfg["max_output_tokens"])
                if gemma_cfg.get("max_output_tokens") not in (None, "")
                else None
            ),
            prompt_manifest=prompt_manifest,
            roles=roles,
            debugger=debugger,
            prompt_cache=prompt_cache,
        )

    if adapter == "gemini":
        if not (
            os.getenv(
                "GEMINI_API_KEY"
            )
            or os.getenv(
                "GOOGLE_API_KEY"
            )
        ):
            raise GeminiConfigurationError(
                "Gemini API Key 未配置。"
                "请设置 GEMINI_API_KEY "
                "或 GOOGLE_API_KEY。"
            )

        return GeminiLLM(
            project_root=project_root,
            model=model,
            prompt_manifest=(
                prompt_manifest
            ),
            roles=roles,
            debugger=debugger,
            prompt_cache=prompt_cache,
        )

    if adapter in {
        "openai",
        "deepseek",
    }:
        provider_cfg = (
            llm_cfg.get(adapter) or {}
        )
        profile_provider_cfg = (
            profile_cfg.get(adapter) or {}
        )
        merged_provider_cfg = {
            **provider_cfg,
            **profile_provider_cfg,
        }

        env_name = (
            "OPENAI_API_KEY"
            if adapter == "openai"
            else "DEEPSEEK_API_KEY"
        )
        api_key = str(
            merged_provider_cfg.get(
                "api_key"
            )
            or os.getenv(env_name)
            or ""
        ).strip()

        if not api_key:
            raise OpenAICompatibleConfigurationError(
                f"{adapter} API Key 未配置。"
                f"请设置 {env_name}。"
            )

        default_base_url = (
            "https://api.openai.com/v1"
            if adapter == "openai"
            else "https://api.deepseek.com"
        )

        deepseek_extra = None
        if adapter == "deepseek":
            thinking_type = str(
                merged_provider_cfg.get("thinking") or "enabled"
            ).strip().lower()
            reasoning_effort = str(
                merged_provider_cfg.get("reasoning_effort") or "high"
            ).strip().lower()
            if thinking_type not in {"enabled", "disabled"}:
                raise OpenAICompatibleConfigurationError(
                    "DEEPSEEK_THINKING 仅支持 enabled 或 disabled。"
                )
            if reasoning_effort not in {"low", "high", "max"}:
                raise OpenAICompatibleConfigurationError(
                    "DEEPSEEK_REASONING_EFFORT 仅支持 low / high / max。"
                )
            deepseek_extra = {
                "thinking": {
                    "type": thinking_type,
                    "reasoning_effort": reasoning_effort,
                }
            }

        return OpenAICompatibleLLM(
            project_root=project_root,
            provider_name=adapter,
            model=model,
            base_url=str(
                merged_provider_cfg.get(
                    "base_url"
                )
                or default_base_url
            ),
            api_key=api_key,
            timeout_seconds=float(
                merged_provider_cfg.get(
                    "timeout_seconds",
                    120,
                )
            ),
            temperature=temperature,
            max_tokens=(
                int(
                    merged_provider_cfg[
                        "max_tokens"
                    ]
                )
                if merged_provider_cfg.get(
                    "max_tokens"
                )
                not in (
                    None,
                    "",
                )
                else None
            ),
            prompt_manifest=(
                prompt_manifest
            ),
            roles=roles,
            prompt_cache=prompt_cache,
            debugger=debugger,
            extra_request_fields=deepseek_extra,
        )

    if adapter == "lmstudio":
        base = (
            llm_cfg.get(
                "lmstudio"
            )
            or {}
        )
        override = (
            profile_cfg.get(
                "lmstudio"
            )
            or {}
        )
        lmstudio_cfg = {
            **base,
            **override,
        }

        return LMStudioLLM(
            project_root=project_root,
            model=model,
            base_url=str(
                lmstudio_cfg.get(
                    "base_url"
                )
                or (
                    "http://127.0.0.1:"
                    "1234/v1"
                )
            ),
            timeout_seconds=float(
                lmstudio_cfg.get(
                    "timeout_seconds",
                    120,
                )
            ),
            temperature=temperature,
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
            prompt_manifest=(
                prompt_manifest
            ),
            roles=roles,
            debugger=debugger,
            prompt_cache=prompt_cache,
        )

    base = (
        llm_cfg.get("ollama")
        or {}
    )
    override = (
        profile_cfg.get("ollama")
        or {}
    )
    ollama_cfg = {
        **base,
        **override,
    }

    return OllamaLLM(
        project_root=project_root,
        model=model,
        base_url=str(
            ollama_cfg.get(
                "base_url"
            )
            or (
                "http://127.0.0.1:"
                "11434"
            )
        ),
        timeout_seconds=float(
            ollama_cfg.get(
                "timeout_seconds",
                120,
            )
        ),
        temperature=temperature,
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
        prompt_manifest=(
            prompt_manifest
        ),
        roles=roles,
        debugger=debugger,
        prompt_cache=prompt_cache,
    )
