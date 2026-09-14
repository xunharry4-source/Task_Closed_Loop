from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from task_closed_loop.integration.models import (
    CapabilityDescriptor,
    ResourceSnapshot,
)
from task_closed_loop.tasks.generation_models import (
    TaskGenerationResult,
)
from task_closed_loop.tasks.models import Task


class TaskListInputError(ValueError):
    pass


def _required_text(
    value: Any,
    field_name: str,
) -> str:
    text = str(value or "").strip()
    if not text:
        raise TaskListInputError(
            f"输入字段 '{field_name}' 必须是非空字符串。"
        )
    return text


def _mapping(
    value: Any,
    field_name: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TaskListInputError(
            f"输入字段 '{field_name}' 必须是 JSON object。"
        )
    return value


@dataclass(frozen=True)
class TaskListRequest:
    resources: tuple[ResourceSnapshot, ...]
    capabilities: tuple[
        CapabilityDescriptor,
        ...
    ]

    @classmethod
    def from_payload(
        cls,
        payload: Any,
    ) -> "TaskListRequest":
        root = _mapping(
            payload,
            "request",
        )

        raw_resources = root.get(
            "resources"
        )
        raw_capabilities = root.get(
            "capabilities"
        )

        if not isinstance(
            raw_resources,
            list,
        ):
            raise TaskListInputError(
                "输入字段 'resources' 必须是 JSON array。"
            )
        if not isinstance(
            raw_capabilities,
            list,
        ):
            raise TaskListInputError(
                "输入字段 'capabilities' 必须是 JSON array。"
            )

        resources = []
        resource_ids: set[str] = set()

        for index, raw in enumerate(
            raw_resources
        ):
            data = _mapping(
                raw,
                f"resources[{index}]",
            )
            resource_id = _required_text(
                data.get("id")
                or data.get(
                    "resource_id"
                ),
                f"resources[{index}].id",
            )
            if resource_id in resource_ids:
                raise TaskListInputError(
                    "resources 中存在重复 id："
                    + resource_id
                )
            resource_ids.add(
                resource_id
            )

            if "payload" not in data:
                raise TaskListInputError(
                    f"resources[{index}] "
                    "缺少必填字段 'payload'。"
                )

            resources.append(
                ResourceSnapshot(
                    resource_id=resource_id,
                    provider_id="user_input",
                    source_identity=(
                        _required_text(
                            data.get(
                                "source_identity"
                            )
                            or resource_id,
                            f"resources[{index}]"
                            ".source_identity",
                        )
                    ),
                    resource_type=(
                        _required_text(
                            data.get("type")
                            or data.get(
                                "resource_type"
                            ),
                            f"resources[{index}]"
                            ".type",
                        )
                    ),
                    payload=data["payload"],
                    revision=(
                        str(
                            data["revision"]
                        )
                        if data.get(
                            "revision"
                        )
                        is not None
                        else None
                    ),
                    availability=str(
                        data.get(
                            "availability",
                            "available",
                        )
                    ).strip()
                    or "available",
                )
            )

        capabilities = []
        capability_ids: set[
            str
        ] = set()

        for index, raw in enumerate(
            raw_capabilities
        ):
            data = _mapping(
                raw,
                f"capabilities[{index}]",
            )
            capability_id = (
                _required_text(
                    data.get("id")
                    or data.get(
                        "capability_id"
                    ),
                    f"capabilities[{index}]"
                    ".id",
                )
            )
            if (
                capability_id
                in capability_ids
            ):
                raise TaskListInputError(
                    "capabilities 中存在重复 id："
                    + capability_id
                )
            capability_ids.add(
                capability_id
            )

            permissions_raw = (
                data.get(
                    "permissions",
                    [],
                )
            )
            if not isinstance(
                permissions_raw,
                (list, tuple),
            ):
                raise TaskListInputError(
                    f"capabilities[{index}]"
                    ".permissions 必须是 array。"
                )

            target_scope = (
                data.get(
                    "target_scope"
                )
                or {}
            )
            if not isinstance(
                target_scope,
                dict,
            ):
                raise TaskListInputError(
                    f"capabilities[{index}]"
                    ".target_scope 必须是 JSON object。"
                )

            capabilities.append(
                CapabilityDescriptor(
                    capability_id=(
                        capability_id
                    ),
                    provider_id=(
                        "user_input"
                    ),
                    action_type=(
                        _required_text(
                            data.get(
                                "action_type"
                            )
                            or capability_id,
                            f"capabilities[{index}]"
                            ".action_type",
                        )
                    ),
                    principal=str(
                        data.get(
                            "principal",
                            "user",
                        )
                    ),
                    security_domain=str(
                        data.get(
                            "security_domain",
                            "user_input",
                        )
                    ),
                    target_scope=(
                        target_scope
                    ),
                    permissions=tuple(
                        _required_text(
                            value,
                            f"capabilities[{index}]"
                            ".permissions[]",
                        )
                        for value
                        in permissions_raw
                    ),
                    description=str(
                        data.get(
                            "description",
                            capability_id,
                        )
                    ),
                    availability=str(
                        data.get(
                            "availability",
                            "available",
                        )
                    ),
                )
            )

        return cls(
            resources=tuple(
                resources
            ),
            capabilities=tuple(
                capabilities
            ),
        )


@dataclass(frozen=True)
class TaskListItem:
    task_id: str
    task_identity: str
    task: str
    user_value: str
    expected_result: str
    execution_steps: tuple[
        str,
        ...
    ]
    reality_basis: str
    status: str

    @classmethod
    def from_task(
        cls,
        task: Task,
    ) -> "TaskListItem":
        return cls(
            task_id=task.task_id,
            task_identity=(
                task.task_identity
            ),
            task=task.description,
            user_value=(
                task.user_value
            ),
            expected_result=(
                task.expected_reality_result
            ),
            execution_steps=tuple(
                task.execution_steps
            ),
            reality_basis=(
                task.reality_basis
            ),
            status=task.status,
        )

    def to_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "task_identity": (
                self.task_identity
            ),
            "task": self.task,
            "user_value": (
                self.user_value
            ),
            "expected_result": (
                self.expected_result
            ),
            "execution_steps": list(
                self.execution_steps
            ),
            "reality_basis": (
                self.reality_basis
            ),
            "status": self.status,
        }


@dataclass(frozen=True)
class TaskListResult:
    tasks: tuple[
        TaskListItem,
        ...
    ]
    generation: (
        TaskGenerationResult
        | None
    ) = None

    def to_payload(
        self,
    ) -> list[dict[str, Any]]:
        return [
            task.to_dict()
            for task in self.tasks
        ]
