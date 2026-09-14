from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Iterable

import yaml

from .models import PreflightCapabilityRecord, PreflightResourceRecord


def _ensure_materialized_output(record: PreflightResourceRecord) -> None:
    normalized_type = record.resource_type.lower().replace("-", "_")
    if "reference" in normalized_type or normalized_type.endswith("_ref"):
        raise ValueError(
            f"Preflight Resource '{record.resource_id}' 仍是引用类型 {record.resource_type}。"
            "Preflight 必须先解析/读取原始路径、URI 或对象引用，再把已物化事实写入 Task 资源文件。"
        )
    if isinstance(record.payload, dict) and record.payload.get("materialized") is False:
        raise ValueError(
            f"Preflight Resource '{record.resource_id}' 尚未物化（materialized=false），"
            "不能写入 Task 层资源文件。"
        )


def _resource_dict(record: PreflightResourceRecord) -> dict:
    _ensure_materialized_output(record)
    return {
        "id": record.resource_id,
        "provider_id": record.provider_id,
        "type": record.resource_type,
        "source_identity": record.source_identity,
        "availability": record.availability,
        "revision": record.revision,
        "payload": record.payload,
        "metadata": record.metadata,
    }


def _capability_dict(record: PreflightCapabilityRecord) -> dict:
    return {
        "id": record.capability_id,
        "provider_id": record.provider_id,
        "action_type": record.action_type,
        "description": record.description,
        "principal": record.principal,
        "security_domain": record.security_domain,
        "availability": record.availability,
        "permissions": list(record.permissions),
        "target_scope": record.target_scope,
        "input_schema": record.input_schema,
        "can_observe_state": record.can_observe_state,
        "observable_state": record.observable_state,
        "observation_operations": list(record.observation_operations),
        "metadata": record.metadata,
    }


def write_preflight_files(
    *,
    resources: Iterable[PreflightResourceRecord],
    capabilities: Iterable[PreflightCapabilityRecord],
    resources_path: str | Path,
    capabilities_path: str | Path,
) -> tuple[Path, Path]:
    """Write the only two contracts consumed by the Task layer.

    The preflight layer may use connectors, local paths, databases, mailboxes,
    cloud drives, or LLM analysis as raw inputs. Raw references must be resolved or
    materialized before this writer emits Task-layer resources. The Task layer only
    consumes standardized materialized facts plus normalized capability semantics.
    """

    r_path = Path(resources_path)
    c_path = Path(capabilities_path)
    r_path.parent.mkdir(parents=True, exist_ok=True)
    c_path.parent.mkdir(parents=True, exist_ok=True)

    r_doc = {
        "schema_version": "1.0",
        "producer": "preflight.resource_analysis",
        "resources": [_resource_dict(item) for item in resources],
    }
    c_doc = {
        "schema_version": "1.0",
        "producer": "preflight.capability_analysis",
        "capabilities": [_capability_dict(item) for item in capabilities],
    }

    r_path.write_text(
        yaml.safe_dump(r_doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    c_path.write_text(
        yaml.safe_dump(c_doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return r_path, c_path
