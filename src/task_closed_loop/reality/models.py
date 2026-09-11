from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

def utc_now(): return datetime.now(timezone.utc)

@dataclass
class EvidenceRecord:
    evidence_id: str
    source_identity: str
    revision_or_time_position: str | None = None
    authority_or_currentness: str | None = None
    availability: str | None = None
    reality_relation: str | None = None
    payload: Any = None

@dataclass
class RealityBuildInput:
    resources: list[Any] = field(default_factory=list)
    evidence: list[EvidenceRecord] = field(default_factory=list)
    external_effects: list[Any] = field(default_factory=list)
    execution_deltas: list[Any] = field(default_factory=list)
    related_history: list[Any] = field(default_factory=list)

@dataclass
class RealitySnapshot:
    reality_id: str
    observed_at: datetime = field(default_factory=utc_now)
    current_facts: dict[str, Any] = field(default_factory=dict)
    current_gaps: list[str] = field(default_factory=list)
    current_conflicts: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    effect_refs: list[str] = field(default_factory=list)
    related_history_refs: list[str] = field(default_factory=list)
    identity_relations: list[dict[str, Any]] = field(default_factory=list)
    suggested_work_relations: list[dict[str, Any]] = field(default_factory=list)
