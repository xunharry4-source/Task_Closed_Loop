from __future__ import annotations

from pathlib import Path
from typing import List

from .base import CliEngineAdapter


class ClaudeCliAdapter(CliEngineAdapter):
    engine_id = "claude_cli"
    executable_name = "claude"

    def auth_probe_command(self, executable: str) -> List[str]:
        # `claude auth status` is explicitly designed for scripting: exit 0 when
        # logged in and 1 when not.  Do not use --bare here or for normal runs,
        # because bare mode intentionally ignores subscription OAuth/keychain auth.
        return [executable, "auth", "status"]

    def build_command(self, *, mode: str, prompt: str, cwd: Path) -> List[str]:
        if mode not in {"analyze", "build"}:
            raise ValueError(f"unsupported Claude mode: {mode}")
        command = [self.executable_name, "-p", prompt, "--output-format", "json"]
        if mode == "analyze":
            command += ["--permission-mode", "plan", "--tools", "Read,Glob,Grep"]
        else:
            command += [
                "--permission-mode",
                "acceptEdits",
                "--tools",
                "Read,Glob,Grep,Edit,Write",
                "--allowedTools",
                "Read,Glob,Grep,Edit,Write",
            ]
        return command
