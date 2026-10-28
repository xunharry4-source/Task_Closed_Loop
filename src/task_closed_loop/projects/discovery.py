"""Step 3: the projects come out of the resources, not out of a hand-kept list.

The chain starts at the project, but a project is not something to configure: it is
read off what the resources actually are. One call groups the resource summaries into
projects; a resource may belong to several (one market-data directory is both the
pipeline's output and every strategy's input).

Two things keep this usable over time:

- **Stable ids.** The task store keys every task, problem, value and demand by
  `entity_id`, and de-duplication plus the "已转任务" write-back depend on it. So a
  project that is the same thing as last round keeps last round's id, matched through a
  registry under `cli_project/state/`.
- **Only re-asked when something changed.** The answer is cached against a fingerprint
  of the resource ids, their summaries and the function names.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Iterable

import yaml

from task_closed_loop.tasks.skill_chain_models import Project, ProjectBinding

STATE_FILE = "projects.yml"

NEW_PROJECT = "new"
REUSED_PROJECT = "reused"
CACHED_PROJECT = "cached"


class ProjectDiscoveryError(RuntimeError):
    pass


@dataclass
class ProjectSet:
    """The projects of this run, and which resources each one is based on."""

    projects: tuple[Project, ...] = ()
    resource_ids: dict[str, tuple[str, ...]] = field(default_factory=dict)
    notes: dict[str, dict[str, str]] = field(default_factory=dict)
    origin: dict[str, str] = field(default_factory=dict)

    def owners_of(self, resource_id: str) -> tuple[ProjectBinding, ...]:
        """Which projects use this resource (the shape `grouping` expects)."""

        resource_id = str(resource_id).strip()
        owners: list[ProjectBinding] = []
        for project in self.projects:
            if resource_id in self.resource_ids.get(project.project_id, ()):
                owners.append(
                    ProjectBinding(
                        project_id=project.project_id,
                        note=self.notes.get(project.project_id, {}).get(resource_id, ""),
                    )
                )
        return tuple(owners)

    def unassigned(self, known_resource_ids: Iterable[str]) -> tuple[str, ...]:
        owned = {
            resource_id
            for ids in self.resource_ids.values()
            for resource_id in ids
        }
        return tuple(
            resource_id for resource_id in known_resource_ids if resource_id not in owned
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "projects": [
                {
                    "id": project.project_id,
                    "name": project.name,
                    "description": project.description,
                    "resource_ids": list(self.resource_ids.get(project.project_id, ())),
                }
                for project in self.projects
            ]
        }


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z一-鿿]+", "_", str(text)).strip("_").lower()
    return cleaned or "project"


def _fingerprint(resource_briefs: Iterable[dict[str, str]], functions: Iterable[str]) -> str:
    payload = json.dumps(
        {
            "resources": sorted(
                (
                    {
                        "id": str(brief.get("resource_id") or ""),
                        "summary": str(brief.get("summary") or ""),
                    }
                    for brief in resource_briefs
                ),
                key=lambda item: item["id"],
            ),
            "functions": sorted(str(name) for name in functions),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _registry_projects(registry: dict[str, Any]) -> list[dict[str, Any]]:
    raw = registry.get("projects")
    return [item for item in (raw or []) if isinstance(item, dict)]


def _stabilize(
    discovered: list[dict[str, Any]],
    *,
    known: list[dict[str, Any]],
) -> tuple[list[Project], dict[str, tuple[str, ...]], dict[str, str]]:
    """Give each project an id that survives across runs."""

    by_id = {str(item.get("id") or ""): item for item in known}
    by_name = {_slug(item.get("name") or ""): item for item in known}
    # Resource sets are not unique: projects legitimately share resources (one market
    # data directory serves the pipeline and every strategy). So a resource-set match
    # only identifies a project when exactly one registry entry has that set.
    resource_candidates: dict[frozenset[str], list[dict[str, Any]]] = {}
    for item in known:
        key = frozenset(str(value) for value in item.get("resource_ids") or ())
        resource_candidates.setdefault(key, []).append(item)

    projects: list[Project] = []
    resource_ids: dict[str, tuple[str, ...]] = {}
    origin: dict[str, str] = {}
    taken: set[str] = set()

    for item in discovered:
        resources = tuple(dict.fromkeys(str(value).strip() for value in item.get("resource_ids") or () if str(value).strip()))
        if not resources:
            continue
        name = str(item.get("name") or "").strip()
        proposed = str(item.get("project_id") or "").strip()

        matched: dict[str, Any] | None = None
        if proposed and proposed in by_id:
            matched = by_id[proposed]
        if matched is None:
            candidate = by_name.get(_slug(name))
            if candidate is not None and set(candidate.get("resource_ids") or ()) & set(resources):
                # Same name, still about at least one of the same resources.
                matched = candidate
        if matched is None:
            same_resources = resource_candidates.get(frozenset(resources)) or []
            if len(same_resources) == 1:
                matched = same_resources[0]

        if matched is not None:
            project_id = str(matched.get("id"))
            origin_kind = REUSED_PROJECT
        else:
            project_id = _slug(proposed or name)
            origin_kind = NEW_PROJECT

        base = project_id
        index = 2
        while project_id in taken:
            project_id = f"{base}_{index}"
            index += 1
        taken.add(project_id)

        projects.append(
            Project(
                project_id=project_id,
                name=name or project_id,
                description=str(item.get("description") or "").strip(),
            )
        )
        resource_ids[project_id] = resources
        origin[project_id] = origin_kind

    return projects, resource_ids, origin


def _write_registry(
    path: Path,
    *,
    fingerprint: str,
    project_set: ProjectSet,
    known: list[dict[str, Any]],
) -> None:
    """Keep projects that disappeared this round: their history still points at them."""

    current = {item["id"]: item for item in project_set.to_payload()["projects"]}
    merged = list(current.values())
    for item in known:
        if str(item.get("id")) not in current:
            merged.append(item)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {"fingerprint": fingerprint, "projects": merged},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )


async def discover_project_set(
    *,
    reasoner,
    resource_briefs: Iterable[dict[str, str]],
    function_names: Iterable[str],
    state_dir: Path,
    logger=None,
) -> ProjectSet:
    briefs = [dict(brief) for brief in resource_briefs]
    functions = [str(name) for name in function_names]
    if not briefs:
        raise ProjectDiscoveryError("没有任何资源可以用来生成项目。")

    state_path = Path(state_dir) / STATE_FILE
    registry = _read_registry(state_path)
    known = _registry_projects(registry)
    fingerprint = _fingerprint(briefs, functions)

    if known and str(registry.get("fingerprint")) == fingerprint:
        projects, resource_ids, _ = _stabilize(
            [
                {
                    "project_id": item.get("id"),
                    "name": item.get("name"),
                    "description": item.get("description"),
                    "resource_ids": item.get("resource_ids"),
                }
                for item in known
            ],
            known=known,
        )
        if logger is not None:
            logger.info("projects.discovery 复用（资源与功能未变）%s", state_path)
        return ProjectSet(
            projects=tuple(projects),
            resource_ids=resource_ids,
            origin={project.project_id: CACHED_PROJECT for project in projects},
        )

    discovered = await reasoner.discover_projects(
        resources=briefs,
        capabilities=functions,
        known_projects=[
            {
                "project_id": item.get("id"),
                "name": item.get("name"),
                "resource_ids": list(item.get("resource_ids") or ()),
            }
            for item in known
        ],
    )
    known_resource_ids = {str(brief.get("resource_id")) for brief in briefs}
    cleaned: list[dict[str, Any]] = []
    for item in discovered or []:
        resources = [
            value for value in item.get("resource_ids") or () if str(value) in known_resource_ids
        ]
        if resources:
            cleaned.append({**item, "resource_ids": resources})

    projects, resource_ids, origin = _stabilize(cleaned, known=known)
    if not projects:
        raise ProjectDiscoveryError(
            "第三步没有生成任何项目：模型没有把资源归进任何项目。"
        )

    project_set = ProjectSet(
        projects=tuple(projects), resource_ids=resource_ids, origin=origin
    )
    _write_registry(state_path, fingerprint=fingerprint, project_set=project_set, known=known)
    if logger is not None:
        logger.info(
            "projects.discovery %s",
            {
                project.project_id: {
                    "name": project.name,
                    "resources": list(resource_ids.get(project.project_id, ())),
                    "origin": origin.get(project.project_id),
                }
                for project in projects
            },
        )
        missing = project_set.unassigned(known_resource_ids)
        if missing:
            logger.warning("projects.discovery 未归入任何项目的资源：%s", list(missing))
    return project_set
