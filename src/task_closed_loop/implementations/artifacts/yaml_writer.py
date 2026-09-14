from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any
import yaml


class YamlProductionArtifactWriter:
    def __init__(self, output_dir: str | Path | None):
        self.output_dir = Path(output_dir).resolve() if output_dir else None

    def _write(self, filename: str, payload: dict[str, Any]) -> Path | None:
        if self.output_dir is None:
            return None
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / filename
        path.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return path

    @staticmethod
    def candidate_payload(candidate):
        return asdict(candidate)

    @staticmethod
    def task_payload(task):
        return {
            "task_id": task.task_id,
            "task_identity": task.task_identity,
            "reality_id": task.reality_id,
            "description": task.description,
            "reality_basis": task.reality_basis,
            "expected_reality_result": task.expected_reality_result,
            "user_value": task.user_value,
            "execution_steps": list(task.execution_steps),
            "status": task.status,
            "metadata": dict(task.metadata),
        }

    def write_initial(self, candidates):
        return self._write(
            "tasks.initial.yml",
            {"schema_version": "1.2", "stage": 3, "status": "unaudited", "tasks": [self.candidate_payload(c) for c in candidates]},
        )

    def write_audited(self, tasks, *, round_number: int):
        return self._write(
            "tasks.audited.yml",
            {"schema_version": "1.2", "stage": 4, "round": round_number, "status": "audited", "tasks": [self.task_payload(t) for t in tasks]},
        )

    def write_dimensions(self, dimensions):
        return self._write(
            "task_dimensions.yml",
            {"schema_version": "1.2", "stage": 6, "dimensions": [asdict(d) for d in dimensions]},
        )

    def write_regenerated(self, candidates, *, round_number: int):
        return self._write(
            f"tasks.regenerated.round_{round_number}.yml",
            {"schema_version": "1.2", "stage": 7, "round": round_number, "status": "unaudited", "tasks": [self.candidate_payload(c) for c in candidates]},
        )

    def write_final(self, tasks):
        return self._write(
            "tasks.final.yml",
            {"schema_version": "1.2", "status": "final_audited_tasks", "tasks": [self.task_payload(t) for t in tasks]},
        )
