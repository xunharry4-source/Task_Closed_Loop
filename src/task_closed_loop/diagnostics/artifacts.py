from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from task_closed_loop.diagnostics.logging import runtime_logger


class RunArtifactStore:
    """Persist per-run debugging artifacts under log/YYYY-MM/<flow_id>."""

    def __init__(
        self,
        project_root: str | Path,
        flow_id: str,
        *,
        started_at: datetime | None = None,
        log_root: str | Path | None = None,
    ):
        timestamp = started_at or datetime.now().astimezone()
        self.flow_id = str(flow_id)
        root = Path(log_root) if log_root else Path(project_root) / "log"
        self.directory = (
            root
            / timestamp.strftime("%Y-%m")
            / self.flow_id
        )

    def write_json(
        self,
        name: str,
        payload: Any,
    ) -> Path | None:
        path = self.directory / name
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    indent=2,
                    default=str,
                )
                + "\n",
                encoding="utf-8",
            )
        except (OSError, TypeError, ValueError) as exc:
            runtime_logger().warning(
                "run_artifact.write_failed flow_id=%s name=%s error=%s",
                self.flow_id,
                name,
                exc,
            )
            return None

        runtime_logger().info(
            "run_artifact.written flow_id=%s name=%s path=%s",
            self.flow_id,
            name,
            path,
        )
        return path
