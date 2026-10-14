"""Projects (entities) declared in config; resource ownership inferred from them.

The chain starts at the project, and the one boundary is the *resource*: a data source
is only ever reasoned about inside the project that owns it. Functions are not split —
every project may use every configured function, so functions declare no ownership.

Ownership itself is worked out by `projects.assignment` from the project descriptions
and what Stage 2 found, and a resource may belong to several projects at once. An
`entities` block on an input stays available as an override for pinning one by hand.

Ownership deliberately does NOT reach the Stage 2 payload: `_unit_fingerprint` hashes
that payload, so adding a field there would force every unit's CLI code to be rebuilt
while changing nothing about what Stage 2 observes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from task_closed_loop.tasks.skill_chain_models import Project, ProjectBinding


class ProjectConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProjectInputBindings:
    projects: tuple[Project, ...]
    # configured input id -> the projects that own it
    bindings: dict[str, tuple[ProjectBinding, ...]] = field(default_factory=dict)
    # configured function id -> the one-line description the user wrote for it
    function_descriptions: dict[str, str] = field(default_factory=dict)
    # configured resource input id -> that one-line description
    resource_descriptions: dict[str, str] = field(default_factory=dict)

    def project_ids(self) -> tuple[str, ...]:
        return tuple(project.project_id for project in self.projects)

    def project(self, project_id: str) -> Project | None:
        for project in self.projects:
            if project.project_id == project_id:
                return project
        return None

    def input_ids_for(self, project_id: str) -> tuple[str, ...]:
        return tuple(
            input_id
            for input_id, owners in self.bindings.items()
            if any(owner.project_id == project_id for owner in owners)
        )

    def binding_for(self, input_id: str, project_id: str) -> ProjectBinding | None:
        for owner in self.bindings.get(input_id, ()):
            if owner.project_id == project_id:
                return owner
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _load_projects(config: dict) -> tuple[Project, ...]:
    raw = (config or {}).get("projects")
    if raw is None:
        raise ProjectConfigurationError(
            "缺少 projects 配置。请在 config/projects.yml 中声明项目（entity_id / name / domain / description）。"
        )
    if not isinstance(raw, list) or not raw:
        raise ProjectConfigurationError("projects 必须是非空列表。")

    projects: list[Project] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ProjectConfigurationError(f"projects[{index}] 必须是映射。")
        project_id = _text(item.get("id"))
        if not project_id:
            raise ProjectConfigurationError(f"projects[{index}] 缺少 id。")
        if project_id in seen:
            raise ProjectConfigurationError(f"projects 中 id 重复：{project_id}")
        description = _text(item.get("description"))
        seen.add(project_id)
        projects.append(
            Project(
                project_id=project_id,
                name=_text(item.get("name")) or project_id,
                domain=_text(item.get("domain")),
                description=description,
            )
        )
    return tuple(projects)


def _parse_entities(
    raw_item: dict,
    *,
    section: str,
    input_id: str,
    known_project_ids: set[str],
) -> tuple[ProjectBinding, ...]:
    raw = raw_item.get("entities")
    if not isinstance(raw, list) or not raw:
        raise ProjectConfigurationError(f"{section} '{input_id}' 的 entities 必须是非空列表。")

    owners: list[ProjectBinding] = []
    seen: set[str] = set()
    for index, entry in enumerate(raw):
        if isinstance(entry, str):
            entry = {"id": entry}
        if not isinstance(entry, dict):
            raise ProjectConfigurationError(
                f"{section} '{input_id}' entities[{index}] 必须是项目 id 或映射。"
            )
        project_id = _text(entry.get("id"))
        if not project_id:
            raise ProjectConfigurationError(f"{section} '{input_id}' entities[{index}] 缺少 id。")
        if project_id not in known_project_ids:
            raise ProjectConfigurationError(
                f"{section} '{input_id}' 归属到未声明的项目 '{project_id}'；"
                f"已声明的项目：{', '.join(sorted(known_project_ids)) or '（无）'}。"
            )
        if project_id in seen:
            raise ProjectConfigurationError(
                f"{section} '{input_id}' 重复归属到同一项目 '{project_id}'。"
            )
        seen.add(project_id)
        owners.append(
            ProjectBinding(
                project_id=project_id,
                role=_text(entry.get("role")),
                note=_text(entry.get("note")),
            )
        )
    return tuple(owners)


def load_project_bindings(config: dict) -> ProjectInputBindings:
    """Read projects + per-input ownership out of the already-merged config dict."""

    projects = _load_projects(config)
    known = {project.project_id for project in projects}

    section = (config or {}).get("preflight_inputs") or {}
    bindings: dict[str, tuple[ProjectBinding, ...]] = {}
    resource_descriptions: dict[str, str] = {}
    function_descriptions: dict[str, str] = {}

    # Only resources are owned. Functions are available to every project, so an
    # `entities` key on a function is ignored rather than silently narrowing it.
    for key in ("local_resources", "remote_resources"):
        items = section.get(key) or []
        if not isinstance(items, list):
            raise ProjectConfigurationError(f"preflight_inputs.{key} 必须是列表。")
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            input_id = _text(item.get("id"))
            if not input_id:
                continue
            resource_descriptions[input_id] = _text(item.get("description"))
            if item.get("entities") is None:
                # Not pinned: the assignment step decides who owns it.
                continue
            bindings[input_id] = _parse_entities(
                item,
                section=key,
                input_id=input_id,
                known_project_ids=known,
            )

    for item in section.get("functions") or []:
        if not isinstance(item, dict):
            continue
        function_id = _text(item.get("id"))
        if function_id:
            function_descriptions[function_id] = _text(item.get("description"))

    return ProjectInputBindings(
        projects=projects,
        bindings=bindings,
        function_descriptions=function_descriptions,
        resource_descriptions=resource_descriptions,
    )
