from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

def utc_now(): return datetime.now(timezone.utc)

@dataclass(frozen=True)
class ProviderManifest:
    provider_id: str
    provider_type: str
    resource_support: tuple[str, ...] = ()
    capability_support: tuple[str, ...] = ()
    principal_refs: tuple[str, ...] = ()
    security_domains: tuple[str, ...] = ()
    connection_state: str = 'available'

@dataclass(frozen=True)
class ResourceRef:
    provider_id: str
    resource_id: str

@dataclass
class ResourceDescriptor:
    resource_id: str
    provider_id: str
    resource_type: str
    source_identity: str

@dataclass
class ResourceSnapshot:
    resource_id: str
    provider_id: str
    source_identity: str
    resource_type: str
    payload: Any
    observed_at: datetime = field(default_factory=utc_now)
    revision: str | None = None
    availability: str = 'available'

@dataclass
class CapabilityDescriptor:
    capability_id: str
    provider_id: str
    action_type: str
    principal: str | None = None
    security_domain: str | None = None
    target_scope: dict[str, Any] = field(default_factory=dict)
    permissions: tuple[str, ...] = ()
    availability: str = 'available'
    description: str | None = None
    input_schema: dict[str, Any] = field(default_factory=dict)
    # Some capabilities can actively observe/query a state domain whose concrete
    # objects are not materialized as Resources yet (mailbox, database, file store,
    # calendar, web, etc.).  This is distinct from a Resource: it authorizes a probe
    # of current reality, but does not assert that any particular object exists.
    can_observe_state: bool = False
    observable_state: str | None = None
    observation_operations: tuple[str, ...] = ()
    observed_at: datetime = field(default_factory=utc_now)

@dataclass(frozen=True)
class CapabilityRef:
    provider_id: str
    capability_id: str

@dataclass
class ExecutionRequest:
    capability_ref: CapabilityRef
    action_type: str
    target: dict[str, Any]
    payload: dict[str, Any]
    execution_intent_id: str
    attempt_id: str

@dataclass
class ExecutionObservation:
    provider_id: str
    attempt_id: str
    target_at_execution: dict[str, Any]
    effect_scope: dict[str, Any]
    commit_knowledge: str
    evidence_refs: tuple[str, ...] = ()
    raw_result: Any = None
    observed_at: datetime = field(default_factory=utc_now)
