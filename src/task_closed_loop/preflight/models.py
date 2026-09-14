from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PreflightResourceRecord:
    """Materialized resource fact produced by Preflight for the Task-layer contract.

    Raw paths/URIs/object references are Preflight inputs, not valid Task resources.
    source_identity should be a stable normalized identity rather than a raw locator.
    """

    resource_id: str
    resource_type: str
    source_identity: str
    payload: Any
    provider_id: str = "preflight"
    availability: str = "available"
    revision: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreflightCapabilityRecord:
    """Standard capability record produced by the preflight capability-analysis layer."""

    capability_id: str
    action_type: str
    provider_id: str = "preflight"
    description: str | None = None
    principal: str | None = None
    security_domain: str | None = None
    permissions: tuple[str, ...] = ()
    target_scope: dict[str, Any] = field(default_factory=dict)
    availability: str = "available"
    input_schema: dict[str, Any] = field(default_factory=dict)
    can_observe_state: bool = False
    observable_state: str | None = None
    observation_operations: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreflightAnalysisResult:
    resources: list[PreflightResourceRecord] = field(default_factory=list)
    capabilities: list[PreflightCapabilityRecord] = field(default_factory=list)
