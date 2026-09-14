from __future__ import annotations

from pathlib import Path
from typing import List

from .base import CliEngineAdapter


class CodexCliAdapter(CliEngineAdapter):
    engine_id = "codex_cli"
    executable_name = "codex"

    def auth_probe_command(self, executable: str) -> List[str]:
        # Codex CLI exposes a non-interactive login status command whose exit code
        # reflects whether credentials are present.
        return [executable, "login", "status"]

    def build_command(self, *, mode: str, prompt: str, cwd: Path) -> List[str]:
        if mode not in {"analyze", "build"}:
            raise ValueError(f"unsupported Codex mode: {mode}")
        sandbox = "read-only" if mode == "analyze" else "workspace-write"
        return [
            self.executable_name,
            "exec",
            "--cd",
            str(cwd),
            "--skip-git-repo-check",
            "--sandbox",
            sandbox,
            "--json",
            prompt,
        ]
