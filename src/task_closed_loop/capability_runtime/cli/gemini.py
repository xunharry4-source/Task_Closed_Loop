from __future__ import annotations

from pathlib import Path
from typing import List

from .base import CliEngineAdapter


class GeminiCliAdapter(CliEngineAdapter):
    engine_id = "gemini_cli"
    executable_name = "gemini"

    def auth_probe_command(self, executable: str) -> List[str]:
        # Gemini CLI has no stable `auth status` subcommand.  A tiny headless,
        # no-tool prompt is the only reliable way to distinguish INSTALLED from a
        # credential that can actually serve requests.  Existing cached auth is used.
        return [
            executable,
            "--prompt",
            "Reply exactly READY.",
            "--output-format",
            "json",
            "--approval-mode",
            "plan",
            "--sandbox",
        ]

    def build_command(self, *, mode: str, prompt: str, cwd: Path) -> List[str]:
        if mode not in {"analyze", "build"}:
            raise ValueError(f"unsupported Gemini mode: {mode}")
        approval_mode = "plan" if mode == "analyze" else "auto_edit"
        return [
            self.executable_name,
            "--prompt",
            prompt,
            "--output-format",
            "json",
            "--approval-mode",
            approval_mode,
            "--sandbox",
        ]
