from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
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

    def write_rejections(self, generation, *, round_number: int):
        """Why this round produced what it produced, before anything is merged away.

        Round 0 is Stage 3 + its Stage 4 audit; round n is Stage 7 round n + its audit.
        The pipeline keeps only the last cycle's trace, so without this file the
        reasons earlier rounds lost their findings and candidates are gone.
        """

        if self.output_dir is None:
            return None
        if round_number == 0:
            # Files from a previous production run would read as this run's rounds.
            for stale in self.output_dir.glob("rejections.round_*.yml"):
                stale.unlink()

        trace = generation.trace
        kept_task_ids = {task.task_id for task in generation.tasks}
        payload = {
            "schema_version": "1.0",
            "round": round_number,
            "written_at": datetime.now(timezone.utc).isoformat(),
            "counts": {
                "findings_accepted": len(trace.discovery_signals),
                "findings_rejected": len(trace.rejected_discovery_reasons),
                "task_ideas": len(trace.discovery_seeds)
                + len(trace.coverage_expansion_seeds)
                + len(trace.proliferation_seeds),
                "task_ideas_rejected": len(trace.seed_validation_errors),
                "task_ideas_failed_to_materialize": len(trace.seed_materialization_errors),
                "candidates": len(generation.discovered_candidates),
                "candidates_rejected": len(trace.rejected_candidate_contexts),
                "candidates_accepted": len(generation.accepted_candidates),
                "tasks_kept": len(generation.tasks),
            },
            "generation": {
                "discovery_error": trace.discovery_error,
                "rejected_findings": dict(trace.rejected_discovery_reasons),
                "rejected_task_ideas": dict(trace.seed_validation_errors),
                "task_ideas_failed_to_materialize": dict(trace.seed_materialization_errors),
                "proliferation_error": trace.proliferation_error,
                "proliferation_rejected_outcomes": dict(trace.proliferation_rejected_outcomes),
            },
            "audit": {
                "rejected_candidates": [asdict(c) for c in trace.rejected_candidate_contexts],
                "structural_findings": [asdict(f) for f in trace.structural_findings],
                "unresolved_field_issues": {
                    key: list(value) for key, value in trace.unresolved_field_issues.items()
                },
                "set_review": asdict(trace.set_review) if trace.set_review is not None else None,
                "fidelity_findings": list(trace.fidelity_findings),
                "reality_validity_findings": list(trace.reality_validity_findings),
                "final_reviews_not_kept": [
                    asdict(review)
                    for review in trace.final_task_reality_reviews
                    if review.task_id not in kept_task_ids
                ],
            },
        }
        return self._write(f"rejections.round_{round_number}.yml", payload)

    def write_final(self, tasks):
        return self._write(
            "tasks.final.yml",
            {"schema_version": "1.2", "status": "final_audited_tasks", "tasks": [self.task_payload(t) for t in tasks]},
        )
