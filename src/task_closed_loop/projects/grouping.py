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

from task_closed_loop.projects.config import ProjectConfigurationError, ProjectInputBindings
from task_closed_loop.tasks.skill_chain_models import ProjectScope

RESOURCES_FILE = "resources.generated.yml"
CAPABILITIES_FILE = "capabilities.generated.yml"


def _read_items(path: Path, key: str) -> list[dict[str, Any]]:
    if not path.exists():
        raise ProjectConfigurationError(f"Stage 2 标准输出不存在：{path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = data.get(key) or []
    if not isinstance(items, list):
        raise ProjectConfigurationError(f"{path} 的 {key} 必须是列表。")
    return [item for item in items if isinstance(item, dict)]


@dataclass
class ProjectScopeResolver:
    generated_dir: Path
    bindings: ProjectInputBindings

    def __post_init__(self) -> None:
        self.generated_dir = Path(self.generated_dir).resolve()
        self._resource_inputs: dict[str, tuple[str, ...]] = {}
        self._capability_function: dict[str, str] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        for item in _read_items(self.generated_dir / RESOURCES_FILE, "resources"):
            resource_id = str(item.get("id") or "").strip()
            metadata = item.get("metadata") or {}
            sources = metadata.get("source_input_ids") if isinstance(metadata, dict) else None
            if resource_id and isinstance(sources, list):
                self._resource_inputs[resource_id] = tuple(
                    str(value).strip() for value in sources if str(value).strip()
                )
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

    def capability_briefs(self, capabilities: Iterable[Any]) -> tuple[str, ...]:
        """Just the function names, one per function.

        Not per operation, and without a blurb: a model already knows what codex or a
        mailbox is, and will look up what it does not know. Spelling out "what this
        function can do" only teaches it that the function can do nothing else.
        """

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

    def resource_briefs(
        self,
        resources: Iterable[Any],
        *,
        project_id: str = "",
        assignment=None,
    ) -> tuple[dict[str, str], ...]:
        """id + the one-line description + (for a project) why it has this resource.

        No payload: the observed detail enters the chain once, through the reality the
        reality builder writes from the full resources. Stage 4 still audits against
        the full objects.
        """

        self._load()
        briefs: list[dict[str, str]] = []
        for resource in resources:
            resource_id = str(resource.resource_id).strip()
            if not resource_id:
                continue
            brief = {"resource_id": resource_id}
            description = ""
            for input_id in self._resource_inputs.get(resource_id, ()):
                description = description or self.bindings.resource_descriptions.get(input_id, "")
            if description:
                brief["description"] = description
            if project_id and assignment is not None:
                for owner in assignment.owners_of(resource_id):
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
        assignment,
    ) -> list[ProjectScope]:
        """One scope per project that owns at least one resource this run."""

        resources = list(resources)
        capabilities = list(capabilities)
        per_project: dict[str, list[Any]] = {}

        for resource in resources:
            for owner in assignment.owners_of(resource.resource_id):
                per_project.setdefault(owner.project_id, []).append(resource)

        shared_capabilities = tuple(capabilities)
        capability_names = self.capability_briefs(capabilities)
        capability_ids = self.capability_ids_by_function()

        scopes: list[ProjectScope] = []
        for project in self.bindings.projects:
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
                        owned, project_id=project.project_id, assignment=assignment
                    ),
                    capability_briefs=capability_names,
                    capability_ids_by_function=capability_ids,
                )
            )
        return scopes
