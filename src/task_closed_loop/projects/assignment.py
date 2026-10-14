"""Which project does a data source belong to? The system works it out.

Hand-writing the mapping does not scale and is not what the chain asks for: its first
step is a classifier that reads the sources and partitions them by project. So the
assignment is inferred from the project descriptions plus what Stage 2 actually found,
and a source may belong to several projects at once — one market-data directory is both
the pipeline's output and every strategy's input.

Two things keep it stable and cheap:

- a configured `entities` block still wins, so anything can be pinned by hand;
- the answer is cached under `cli_project/state/` against a fingerprint of the projects
  and resources involved, so it is re-asked only when one of them changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import yaml

from task_closed_loop.projects.config import ProjectInputBindings
from task_closed_loop.tasks.skill_chain_models import ProjectBinding

STATE_FILE = "project_assignment.yml"

CONFIG_SOURCE = "config"
INFERRED_SOURCE = "inferred"
CACHED_SOURCE = "cached"


@dataclass
class ResourceAssignment:
    """resource_id -> the projects that own it, plus where that came from."""

    by_resource: dict[str, tuple[ProjectBinding, ...]] = field(default_factory=dict)
    origin: dict[str, str] = field(default_factory=dict)

    def owners_of(self, resource_id: str) -> tuple[ProjectBinding, ...]:
        return self.by_resource.get(str(resource_id).strip(), ())

    def unassigned(self) -> tuple[str, ...]:
        return tuple(
            resource_id
            for resource_id, owners in self.by_resource.items()
            if not owners
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            resource_id: [
                {"project_id": owner.project_id, "note": owner.note, "role": owner.role}
                for owner in owners
            ]
            for resource_id, owners in sorted(self.by_resource.items())
        }


def _fingerprint(*, projects: Iterable[Any], resource_briefs: Iterable[dict[str, str]]) -> str:
    payload = json.dumps(
        {
            "projects": sorted(
                (
                    {
                        "id": project.project_id,
                        "name": project.name,
                        "description": project.description,
                    }
                    for project in projects
                ),
                key=lambda item: item["id"],
            ),
            "resources": sorted(
                (dict(brief) for brief in resource_briefs),
                key=lambda item: item.get("resource_id", ""),
            ),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _write_state(path: Path, *, fingerprint: str, assignment: ResourceAssignment) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {"fingerprint": fingerprint, "assignments": assignment.to_payload()},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _bindings_from_payload(
    raw: Any,
    *,
    known_project_ids: set[str],
) -> tuple[ProjectBinding, ...]:
    owners: list[ProjectBinding] = []
    for entry in raw or ():
        if isinstance(entry, str):
            entry = {"project_id": entry}
        if not isinstance(entry, dict):
            continue
        project_id = str(entry.get("project_id") or "").strip()
        if not project_id or project_id not in known_project_ids:
            continue
        if any(owner.project_id == project_id for owner in owners):
            continue
        owners.append(
            ProjectBinding(
                project_id=project_id,
                role=str(entry.get("role") or "").strip(),
                note=str(entry.get("note") or "").strip(),
            )
        )
    return tuple(owners)


async def resolve_resource_assignment(
    *,
    reasoner,
    bindings: ProjectInputBindings,
    resource_briefs: Iterable[dict[str, str]],
    resource_inputs: dict[str, tuple[str, ...]],
    reality: Any = None,
    state_dir: Path,
    logger=None,
) -> ResourceAssignment:
    briefs = [dict(brief) for brief in resource_briefs]
    known = {project.project_id for project in bindings.projects}
    assignment = ResourceAssignment()

    # 1. anything the user pinned in config wins and is never asked about.
    pending: list[dict[str, str]] = []
    for brief in briefs:
        resource_id = str(brief.get("resource_id") or "").strip()
        if not resource_id:
            continue
        configured: list[ProjectBinding] = []
        for input_id in resource_inputs.get(resource_id, ()):
            for owner in bindings.bindings.get(input_id, ()):
                if not any(item.project_id == owner.project_id for item in configured):
                    configured.append(owner)
        if configured:
            assignment.by_resource[resource_id] = tuple(configured)
            assignment.origin[resource_id] = CONFIG_SOURCE
        else:
            pending.append(brief)

    if not pending:
        return assignment

    # 2. reuse the cached answer while the projects and resources are unchanged.
    state_path = Path(state_dir) / STATE_FILE
    fingerprint = _fingerprint(projects=bindings.projects, resource_briefs=briefs)
    state = _read_state(state_path)
    cached = state.get("assignments") if str(state.get("fingerprint")) == fingerprint else None
    if isinstance(cached, dict):
        for brief in pending:
            resource_id = str(brief.get("resource_id"))
            assignment.by_resource[resource_id] = _bindings_from_payload(
                cached.get(resource_id), known_project_ids=known
            )
            assignment.origin[resource_id] = CACHED_SOURCE
        if logger is not None:
            logger.info("projects.assignment reused (unchanged) %s", state_path)
        return assignment

    # 3. otherwise ask, then cache.
    projects_payload = [
        {
            "project_id": project.project_id,
            "name": project.name,
            "description": project.description,
        }
        for project in bindings.projects
    ]
    answered = await reasoner.assign_resources_to_projects(
        projects=projects_payload,
        resources=pending,
        reality=reality,
    )
    for brief in pending:
        resource_id = str(brief.get("resource_id"))
        owners = _bindings_from_payload(
            [
                {"project_id": project_id, "note": note}
                for project_id, note in answered.get(resource_id, ())
            ],
            known_project_ids=known,
        )
        assignment.by_resource[resource_id] = owners
        assignment.origin[resource_id] = INFERRED_SOURCE

    _write_state(state_path, fingerprint=fingerprint, assignment=assignment)
    if logger is not None:
        logger.info(
            "projects.assignment inferred %s",
            {
                resource_id: [owner.project_id for owner in owners]
                for resource_id, owners in assignment.by_resource.items()
            },
        )
    return assignment
