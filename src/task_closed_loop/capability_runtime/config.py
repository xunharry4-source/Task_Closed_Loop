from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any

from .io_utils import read_yaml
from .errors import ExecutionProjectError


@dataclass(frozen=True)
class ProjectConfig:
    root: Path
    raw: Dict[str, Any]

    @classmethod
    def load(cls, root: Path) -> "ProjectConfig":
        root = Path(root).resolve()
        path = root / "project.yml"
        if not path.exists():
            raise ExecutionProjectError(f"missing project.yml: {path}")
        data = read_yaml(path)
        if data.get("project_role") != "persistent_capability_workspace":
            raise ExecutionProjectError("project.yml is not an Execution Project")
        return cls(root=root, raw=data)

    def path(self, key: str) -> Path:
        rel = self.raw.get("paths", {}).get(key)
        if not rel:
            raise ExecutionProjectError(f"project.yml missing paths.{key}")
        return (self.root / rel).resolve()
