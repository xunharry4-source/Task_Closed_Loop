"""Split Stage 2's standard output into per-project scopes.

Only *resources* are split. Functions are the system's own toolbox — codex, a mailbox,
a database client — and every project may use all of them, so capabilities go to each
project whole, as bare names.

Which project a resource belongs to is decided by `projects.assignment` (inferred, with
a configured override); this module only applies that decision. Provenance
(`metadata.source_input_ids`) is read back from the standard file the architecture
fixes, because `ResourceSnapshot` has no metadata field and the link is otherwise lost
at the Stage 2 -> Stage 3 boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

from task_closed_loop.tasks.skill_chain_models import ProjectScope


class ProjectScopeError(RuntimeError):
    pass

RESOURCES_FILE = "resources.generated.yml"
CAPABILITIES_FILE = "capabilities.generated.yml"


def _read_items(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.exists():
        raise ProjectScopeError(f"Stage 2 标准输出不存在：{path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = data.get(key) or []
    if not isinstance(items, list):
        raise ProjectScopeError(f"{path} 的 {key} 必须是列表。")
    return [item for item in items if isinstance(item, dict)]


@dataclass
class ProjectScopeResolver:
    generated_dir: Path

    def __post_init__(self) -> None:
        self.generated_dir = Path(self.generated_dir).resolve()
        self._resource_inputs: dict[str, tuple[str, ...]] = {}
        self._resource_summaries: dict[str, str] = {}
        self._resource_types: dict[str, str] = {}
        self._capability_function: dict[str, str] = {}
        self._capability_identity: dict[str, str] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        for item in _read_items(self.generated_dir / RESOURCES_FILE, "resources"):
            resource_id = str(item.get("id") or "").strip()
            metadata = item.get("metadata") or {}
            sources = metadata.get("source_input_ids") if isinstance(metadata, dict) else None
            if not resource_id:
                continue
            if isinstance(sources, list):
                self._resource_inputs[resource_id] = tuple(
                    str(value).strip() for value in sources if str(value).strip()
                )
            self._resource_summaries[resource_id] = str(item.get("summary") or "").strip()
            self._resource_types[resource_id] = str(item.get("type") or "").strip()
        for item in _read_items(self.generated_dir / CAPABILITIES_FILE, "capabilities"):
            capability_id = str(item.get("id") or "").strip()
            metadata = item.get("metadata") or {}
            function_id = (
                str(metadata.get("source_function_id") or "").strip()
                if isinstance(metadata, dict)
                else ""
            )
            if capability_id:
                self._capability_function[capability_id] = function_id
                identity = str(item.get("identity") or "").strip()
                if identity:
                    self._capability_identity[function_id or capability_id] = identity
        self._loaded = True

    # -- provenance ---------------------------------------------------------

    def resource_inputs(self) -> dict[str, tuple[str, ...]]:
        """resource_id -> the configured input ids it came from."""

        self._load()
        return dict(self._resource_inputs)

    def input_id_of_resource(self, resource_id: str) -> tuple[str, ...]:
        self._load()
        return self._resource_inputs.get(str(resource_id).strip(), ())

    def capability_ids_by_function(self) -> dict[str, tuple[str, ...]]:
        """function name -> the capability ids Stage 2 actually reported for it."""

        self._load()
        out: dict[str, list[str]] = {}
        for capability_id, function_id in self._capability_function.items():
            out.setdefault(function_id or capability_id, []).append(capability_id)
        return {key: tuple(sorted(value)) for key, value in out.items()}

    # -- what the model sees ------------------------------------------------

    def capability_names(self, capabilities: Iterable[Any]) -> tuple[str, ...]:
        """The function names, one per function — not per operation."""

        self._load()
        names: list[str] = []
        for capability in capabilities:
            capability_id = str(capability.capability_id).strip()
            if not capability_id:
                continue
            function_id = self._capability_function.get(capability_id) or capability_id
            if function_id not in names:
                names.append(function_id)
        return tuple(names)

    def capability_briefs(self, capabilities: Iterable[Any]) -> tuple[dict[str, str], ...]:
        """Name + identity, one entry per function.

        `identity` says who made it and what kind of tool it is — never what it can do.
        A model already knows codex or a mailbox, and looks up what it does not know;
        an ability list would only teach it that the function can do nothing else.
        """

        self._load()
        briefs: list[dict[str, str]] = []
        for function_id in self.capability_names(capabilities):
            brief = {"function": function_id}
            identity = self._capability_identity.get(function_id, "")
            if identity:
                brief["identity"] = identity
            briefs.append(brief)
        return tuple(briefs)

    def resource_briefs(
        self,
        resources: Iterable[Any],
        *,
        project_id: str = "",
        project_set=None,
    ) -> tuple[dict[str, str], ...]:
        """id + the analysis `summary` + (for a project) why it has this resource.

        No payload. `summary` is the one line the analysis wrote — what this is, what it
        holds now, how far along it is — and it is what every step after Stage 2 reads.
        Stage 4 still audits against the full resource objects.
        """

        self._load()
        briefs: list[dict[str, str]] = []
        for resource in resources:
            resource_id = str(resource.resource_id).strip()
            if not resource_id:
                continue
            brief = {"resource_id": resource_id}
            summary = self._resource_summaries.get(resource_id, "")
            if not summary:
                # Saved templates from before `summary` existed: say what little is known
                # rather than pretending.
                resource_type = self._resource_types.get(resource_id, "")
                summary = f"（分析未提供 summary）{resource_type}".strip()
            brief["summary"] = summary
            if project_id and project_set is not None:
                for owner in project_set.owners_of(resource_id):
                    if owner.project_id == project_id and (owner.note or owner.role):
                        brief["note"] = owner.note or owner.role
                        break
            briefs.append(brief)
        return tuple(briefs)

    # -- the split ----------------------------------------------------------

    def scopes(
        self,
        resources: Iterable[Any],
        capabilities: Iterable[Any],
        project_set,
    ) -> list[ProjectScope]:
        """One scope per discovered project, with the resources it is based on."""

        resources = list(resources)
        capabilities = list(capabilities)
        per_project: dict[str, list[Any]] = {}

        for resource in resources:
            for owner in project_set.owners_of(resource.resource_id):
                per_project.setdefault(owner.project_id, []).append(resource)

        shared_capabilities = tuple(capabilities)
        capability_names = self.capability_briefs(capabilities)
        capability_ids = self.capability_ids_by_function()

        scopes: list[ProjectScope] = []
        for project in project_set.projects:
            owned = per_project.get(project.project_id, [])
            if not owned:
                # No resources of its own means nothing for this project to work on;
                # the shared function list alone is not a subject.
                continue
            scopes.append(
                ProjectScope(
                    project=project,
                    resources=tuple(owned),
                    capabilities=shared_capabilities,
                    resource_briefs=self.resource_briefs(
                        owned, project_id=project.project_id, project_set=project_set
                    ),
                    capability_briefs=capability_names,
                    capability_ids_by_function=capability_ids,
                )
            )
        return scopes
