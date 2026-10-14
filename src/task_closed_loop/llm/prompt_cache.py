from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from task_closed_loop.diagnostics.logging import runtime_logger
from task_closed_loop.diagnostics.logging import create_flow_id


_SAFE_NAME = re.compile(r"[^A-Za-z0-9_.-]+")


class PromptRequestCache:
    """Best-effort local cache of prompts immediately before an LLM call."""

    def __init__(
        self,
        directory: str | Path,
        *,
        enabled: bool = True,
        flow_id: str = "-",
    ):
        self.directory = Path(directory)
        self.enabled = bool(enabled)
        self.flow_id = str(flow_id)

    def record(
        self,
        *,
        provider: str,
        model: str,
        role_key: str,
        prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> Path | None:
        """Write the exact prompt right before the call.

        Before, not after: a call that hangs, is killed, or dies in the CLI is exactly
        the one whose prompt you need.
        """

        if not self.enabled:
            return None

        prompt_text = str(prompt)
        prompt_hash = hashlib.sha256(
            prompt_text.encode("utf-8")
        ).hexdigest()
        created_at = datetime.now(timezone.utc).isoformat()
        request_id = str(uuid4())
        record = {
            "request_id": request_id,
            "flow_id": self.flow_id,
            "created_at": created_at,
            "provider": str(provider),
            "model": str(model),
            "role_key": str(role_key),
            "prompt_sha256": prompt_hash,
            "prompt": prompt_text,
            "metadata": dict(metadata or {}),
        }

        filename = "_".join(
            (
                datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H-%M-%S.%fZ"
                ),
                _SAFE_NAME.sub("_", str(role_key)),
                prompt_hash[:12],
                request_id[:8],
            )
        ) + ".json"
        path = self.directory / filename

        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    record,
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        except (OSError, TypeError, ValueError) as exc:
            runtime_logger().warning(
                "llm.prompt_cache.write_failed role=%s model=%s error=%s",
                role_key,
                model,
                exc,
            )
            return None

        runtime_logger().info(
            "llm.prompt_cache.written role=%s model=%s sha256=%s path=%s",
            role_key,
            model,
            prompt_hash[:16],
            path,
        )
        return path


    def record_response(
        self,
        *,
        provider: str,
        model: str,
        role_key: str,
        response: str,
        metadata: dict[str, Any] | None = None,
    ) -> Path | None:
        """Write what the model actually answered, next to the prompts."""

        if not self.enabled:
            return None

        response_text = str(response)
        response_hash = hashlib.sha256(response_text.encode("utf-8")).hexdigest()
        record = {
            "flow_id": self.flow_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "provider": str(provider),
            "model": str(model),
            "role_key": str(role_key),
            "response_sha256": response_hash,
            "response": response_text,
            "metadata": dict(metadata or {}),
        }
        filename = "_".join(
            (
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S.%fZ"),
                _SAFE_NAME.sub("_", str(role_key)),
                "response",
                response_hash[:12],
            )
        ) + ".json"
        path = self.directory / filename
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except (OSError, TypeError, ValueError) as exc:
            runtime_logger().warning(
                "llm.prompt_cache.response_write_failed role=%s model=%s error=%s",
                role_key,
                model,
                exc,
            )
            return None
        return path


def build_prompt_cache(
    config: dict[str, Any],
    project_root: str | Path,
    flow_id: str | None = None,
) -> PromptRequestCache:
    diagnostics = config.get("diagnostics") or {}
    cache_config = diagnostics.get("prompt_cache") or {}
    directory = Path(
        str(
            os.getenv("TASK_CLOSED_LOOP_LOG_DIR")
            or cache_config.get("directory")
            or "log"
        )
    )
    if not directory.is_absolute():
        directory = Path(project_root) / directory

    active_flow_id = str(flow_id or create_flow_id())
    month = datetime.now().astimezone().strftime("%Y-%m")
    prompt_directory = directory / month / active_flow_id / "prompts"
    return PromptRequestCache(
        prompt_directory,
        enabled=bool(cache_config.get("enabled", False)),
        flow_id=active_flow_id,
    )
