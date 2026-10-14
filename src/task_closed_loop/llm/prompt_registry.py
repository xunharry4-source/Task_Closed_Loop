from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml


class PromptRegistry:
    def __init__(self, project_root: str | Path, manifest_path: str | Path):
        self.project_root = Path(project_root)
        manifest = Path(manifest_path)
        if not manifest.is_absolute():
            manifest = self.project_root / manifest

        with manifest.open("r", encoding="utf-8") as f:
            self._manifest = yaml.safe_load(f) or {}

        self._manifest_path = manifest
        self._prompt_dir = manifest.parent

    def names(self) -> tuple[str, ...]:
        return tuple(self._manifest.get("prompts", {}).keys())

    def get(self, name: str) -> str:
        entry = self._manifest["prompts"][name]
        path = self._prompt_dir / entry["file"]
        text = path.read_text(encoding="utf-8")
        # Shared sections (e.g. the Stage 3-7 input/output contract) are appended from
        # one file, so every role and every adapter sees exactly the same contract.
        for include in entry.get("includes") or ():
            included = self._manifest["prompts"][include]
            if included.get("includes"):
                raise ValueError(f"Prompt include {include} must not include other prompts.")
            text = (
                text.rstrip()
                + "\n\n"
                + (self._prompt_dir / included["file"]).read_text(encoding="utf-8")
            )
        return text

    def role(self, name: str) -> str:
        return str(self._manifest["prompts"][name]["role"])
