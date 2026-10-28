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
    # One line: what this is, what it holds now, how far along it is. Every step after
    # Stage 2 reads this instead of the payload.
    summary: str = ""
    provider_id: str = "preflight"
    availability: str = "available"
    revision: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PreflightCapabilityRecord:
    """One record per configured function: its name and whether it is available.

    Everything else is optional. An operation inventory, a scope or a schema would read
    as the function's ceiling, and the task layer deliberately works from the name
    alone.
    """

    capability_id: str
    action_type: str = ""
    # Who made it and what kind of tool it is — never what it can do.
    identity: str = ""
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
