from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from task_closed_loop.integration.models import CapabilityDescriptor, ResourceSnapshot


class TaskInputConfigurationError(ValueError):
    """Raised when preflight-produced task input files violate the task-layer contract."""


def _looks_like_raw_locator(value: str) -> bool:
    text = value.strip()
    lowered = text.lower()
    locator_prefixes = (
        "http://", "https://", "file://", "s3://", "gs://", "drive://",
        "postgres://", "postgresql://", "mysql://", "sqlite://", "mongodb://",
        "redis://", "ftp://", "sftp://", "smb://",
    )
    if lowered.startswith(locator_prefixes):
        return True
    if len(text) >= 3 and text[1:3] in {":/", ":\\"} and text[0].isalpha():
        return True
    if text.startswith("\\\\") or text.startswith("/mnt/") or text.startswith("/home/"):
        return True
    return False




_RAW_RESOURCE_KEYS = {
    "path", "root", "uri", "url", "dsn", "connection", "connection_string",
    "host", "port", "credentials", "credential", "password", "token", "api_key",
    "secret", "access_token", "refresh_token", "client_secret", "private_key",
}
_CONTENT_LIKE_KEYS = {
    "content", "body", "text", "summary", "description", "subject", "snippet",
    "message", "value", "raw_text",
}


def _validate_task_resource_payload(resource_id: str, payload: Any) -> None:
    """Reject Preflight transport/connection material anywhere in Task payload.

    Materialized user content may naturally *mention* URLs or paths, so locator-looking
    strings are tolerated under explicit content-like fields.  Structural keys that
    carry connection/location semantics are never allowed, even when deeply nested.
    """

    leaked: list[str] = []

    def walk(value: Any, path: tuple[str, ...], parent_key: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key)
                key_lower = key_text.strip().lower()
                child_path = path + (key_text,)
                if key_lower in _RAW_RESOURCE_KEYS:
                    leaked.append(".".join(child_path))
                walk(child, child_path, key_lower)
            return
        if isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                walk(child, path + (f"[{index}]",), parent_key)
            return
        if isinstance(value, str) and parent_key not in _CONTENT_LIKE_KEYS and _looks_like_raw_locator(value):
            leaked.append(".".join(path) + f"={value}")

    walk(payload, ("payload",))
    if leaked:
        raise TaskInputConfigurationError(
            f"Resource '{resource_id}' payload 泄漏 Preflight 原始定位/连接/凭据信息："
            + ", ".join(sorted(set(leaked)))
            + "。Task 层只接受已经物化的事实内容；连接参数必须停留在 Stage 2。"
        )


def _validate_materialized_task_resource(
    *, resource_id: str, resource_type: str, source_identity: str, payload: Any
) -> None:
    normalized_type = resource_type.lower().replace("-", "_")
    if "reference" in normalized_type or normalized_type.endswith("_ref"):
        raise TaskInputConfigurationError(
            f"Resource '{resource_id}' 仍是 Resource Reference（type={resource_type}）。"
            "原始路径/URI/对象引用必须在 Preflight 层解析并物化后，才能进入 Task 层。"
        )
    if isinstance(payload, dict) and payload.get("materialized") is False:
        raise TaskInputConfigurationError(
            f"Resource '{resource_id}' 标记 materialized=false。Task 层只接受已经物化的资源事实。"
        )
    if _looks_like_raw_locator(source_identity):
        raise TaskInputConfigurationError(
            f"Resource '{resource_id}' 的 source_identity 仍是原始路径/URI：{source_identity}。"
            "Preflight 应输出稳定的标准身份与已物化内容，Task Runtime 不解析原始定位信息。"
        )
    _validate_task_resource_payload(resource_id, payload)


def _validate_task_capability_scope(capability_id: str, target_scope: dict[str, Any]) -> None:
    raw_locator_keys = {
        "path", "root", "uri", "url", "dsn", "connection", "connection_string",
        "host", "port", "credentials", "credential", "token", "api_key", "secret",
    }
    leaked: list[str] = []

    def walk(value: Any, path: tuple[str, ...]) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                key_text = str(key)
                child_path = path + (key_text,)
                if key_text.lower() in raw_locator_keys:
                    leaked.append(".".join(child_path))
                walk(child, child_path)
            return
        if isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                walk(child, path + (f"[{index}]",))
            return
        if isinstance(value, str) and _looks_like_raw_locator(value):
            leaked.append(".".join(path) + f"={value}")

    walk(target_scope, ("target_scope",))
    if leaked:
        raise TaskInputConfigurationError(
            f"Capability '{capability_id}' target_scope 泄漏 Preflight 原始定位/连接信息："
            + ", ".join(sorted(set(leaked)))
            + "。Task 层只能消费标准化逻辑作用域，不得接收或解释路径、URI、连接串或凭据。"
        )


@dataclass(frozen=True)
class TaskInputBundle:
    resources: tuple[ResourceSnapshot, ...]
    capabilities: tuple[CapabilityDescriptor, ...]
    resources_path: Path
    capabilities_path: Path


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise TaskInputConfigurationError(
            f"缺少 Task 层输入文件：{path}。正式运行应先由 Preflight 层生成；"
            "本地 Task 测试可直接手写标准资源/功能文件。"
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise TaskInputConfigurationError(f"YAML 根节点必须是 mapping：{path}")
    return raw


def _normalize_resource(item: Any, *, provider_id: str) -> ResourceSnapshot:
    if not isinstance(item, dict):
        raise TaskInputConfigurationError("每条 resources 项必须是 mapping。")

    resource_id = str(item.get("id") or item.get("resource_id") or "").strip()
    resource_type = str(item.get("type") or item.get("resource_type") or "").strip()
    if not resource_id:
        raise TaskInputConfigurationError("Resource 缺少 id。")
    if not resource_type:
        raise TaskInputConfigurationError(f"Resource '{resource_id}' 缺少 type。")

    if "payload" in item:
        payload = item.get("payload")
    elif "fact" in item:
        payload = {"fact": item.get("fact")}
    else:
        raise TaskInputConfigurationError(
            f"Resource '{resource_id}' 必须包含 payload 或 fact。"
        )

    source_identity = str(item.get("source_identity") or resource_id)
    _validate_materialized_task_resource(
        resource_id=resource_id,
        resource_type=resource_type,
        source_identity=source_identity,
        payload=payload,
    )

    return ResourceSnapshot(
        resource_id=resource_id,
        provider_id=str(item.get("provider_id") or provider_id),
        source_identity=source_identity,
        resource_type=resource_type,
        payload=payload,
        revision=(str(item["revision"]) if item.get("revision") is not None else None),
        availability=str(item.get("availability", "available")),
    )


def _normalize_capability(item: Any, *, provider_id: str) -> CapabilityDescriptor:
    if not isinstance(item, dict):
        raise TaskInputConfigurationError(
            "每条 capabilities 项必须是 mapping；Task 层不再从字符串名称猜功能语义。"
        )

    capability_id = str(item.get("id") or item.get("capability_id") or "").strip()
    if not capability_id:
        raise TaskInputConfigurationError("Capability 缺少 id。")

    observation = item.get("observation") or {}
    if not isinstance(observation, dict):
        raise TaskInputConfigurationError(
            f"Capability '{capability_id}' observation 必须是 mapping。"
        )

    # Important architectural boundary: the Task layer consumes semantic facts
    # already produced by Preflight. It never infers observability from names,
    # descriptions, permissions, vendors, or verbs such as read/search/list.
    if "enabled" in observation:
        can_observe_state = bool(observation.get("enabled"))
    else:
        can_observe_state = bool(item.get("can_observe_state", False))

    observable_state = (
        observation.get("state_domain")
        or observation.get("description")
        or item.get("observable_state")
    )
    observable_state = (
        str(observable_state).strip() if observable_state is not None else None
    ) or None

    operations = (
        observation.get("operations")
        if "operations" in observation
        else item.get("observation_operations", [])
    )
    if operations is None:
        operations = []
    if not isinstance(operations, (list, tuple)):
        raise TaskInputConfigurationError(
            f"Capability '{capability_id}' observation operations 必须是 list。"
        )
    observation_operations = tuple(str(value) for value in operations)

    if can_observe_state and not observable_state:
        raise TaskInputConfigurationError(
            f"Capability '{capability_id}' 已声明 can_observe_state=true，"
            "但缺少 observable_state/state_domain。该语义必须由 Preflight 层明确生成。"
        )
    if can_observe_state and not observation_operations:
        raise TaskInputConfigurationError(
            f"Capability '{capability_id}' 已声明 can_observe_state=true，"
            "但缺少 observation_operations。"
        )

    permissions = item.get("permissions", [])
    if not isinstance(permissions, (list, tuple)):
        raise TaskInputConfigurationError(
            f"Capability '{capability_id}' permissions 必须是 list。"
        )
    target_scope = item.get("target_scope") or {}
    if not isinstance(target_scope, dict):
        raise TaskInputConfigurationError(
            f"Capability '{capability_id}' target_scope 必须是 mapping。"
        )
    _validate_task_capability_scope(capability_id, target_scope)

    return CapabilityDescriptor(
        capability_id=capability_id,
        provider_id=str(item.get("provider_id") or provider_id),
        action_type=str(item.get("action_type") or capability_id).strip(),
        principal=(str(item["principal"]) if item.get("principal") is not None else None),
        security_domain=(
            str(item["security_domain"])
            if item.get("security_domain") is not None
            else None
        ),
        target_scope=dict(target_scope),
        permissions=tuple(str(value) for value in permissions),
        availability=str(item.get("availability", "available")),
        description=(
            str(item["description"]) if item.get("description") is not None else None
        ),
        input_schema=dict(item.get("input_schema") or {}),
        can_observe_state=can_observe_state,
        observable_state=observable_state,
        observation_operations=observation_operations,
    )


def load_task_input_bundle(
    resources_path: str | Path,
    capabilities_path: str | Path,
    *,
    project_root: str | Path | None = None,
    provider_id: str = "prepared_input",
) -> TaskInputBundle:
    root = Path(project_root).resolve() if project_root is not None else None

    def resolve(value: str | Path) -> Path:
        path = Path(value)
        if path.is_absolute() or root is None:
            return path
        return root / path

    r_path = resolve(resources_path)
    c_path = resolve(capabilities_path)

    resource_doc = _read_yaml(r_path)
    capability_doc = _read_yaml(c_path)

    resources_raw = resource_doc.get("resources", [])
    capabilities_raw = capability_doc.get("capabilities", [])
    if not isinstance(resources_raw, list):
        raise TaskInputConfigurationError(f"{r_path} 中 resources 必须是 list。")
    if not isinstance(capabilities_raw, list):
        raise TaskInputConfigurationError(f"{c_path} 中 capabilities 必须是 list。")

    resources = tuple(
        _normalize_resource(item, provider_id=provider_id) for item in resources_raw
    )
    capabilities = tuple(
        _normalize_capability(item, provider_id=provider_id) for item in capabilities_raw
    )

    resource_ids = [str(item.resource_id) for item in resources]
    duplicate_resource_ids = sorted({x for x in resource_ids if resource_ids.count(x) > 1})
    if duplicate_resource_ids:
        raise TaskInputConfigurationError(
            "Task 层 Resource ID 必须唯一；发现重复 id："
            + ", ".join(duplicate_resource_ids)
        )

    capability_ids = [str(item.capability_id) for item in capabilities]
    duplicate_capability_ids = sorted({x for x in capability_ids if capability_ids.count(x) > 1})
    if duplicate_capability_ids:
        raise TaskInputConfigurationError(
            "Task 层 Capability ID 必须唯一；发现重复 id："
            + ", ".join(duplicate_capability_ids)
        )

    # Task discovery may legitimately begin with no materialized Resource when
    # observable capabilities exist, so empty resources are allowed.
    if not resources and not capabilities:
        raise TaskInputConfigurationError(
            "Task 层输入同时没有 Resource 和 Capability；没有可分析的现实或功能。"
        )

    return TaskInputBundle(
        resources=resources,
        capabilities=capabilities,
        resources_path=r_path,
        capabilities_path=c_path,
    )
