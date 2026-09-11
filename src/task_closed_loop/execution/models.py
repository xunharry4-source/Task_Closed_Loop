from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

def utc_now(): return datetime.now(timezone.utc)

@dataclass
class ExecutionIntent:
    execution_intent_id: str
    task_id: str
    action_scope: dict[str, Any]
    status: str='open'

@dataclass
class ExecutionContext:
    principal: str | None
    security_domain: str | None
    capabilities: tuple[str, ...]
    ownership: str | None
    approval: str | None
    temporal_context: dict[str, Any]
    current_target: dict[str, Any]

@dataclass
class Attempt:
    attempt_id: str
    execution_intent_id: str
    target_at_execution: dict[str, Any]
    action_scope: dict[str, Any]
    context_snapshot: ExecutionContext
    started_at: datetime = field(default_factory=utc_now)

    @classmethod
    def create(cls, intent, target, context):
        return cls(str(uuid4()), intent.execution_intent_id, dict(target), dict(intent.action_scope), context)

@dataclass
class ExternalEffect:
    effect_id: str
    attempt_id: str
    execution_intent_id: str
    target_at_execution: dict[str, Any]
    effect_scope: dict[str, Any]
    commit_knowledge: str
    evidence_refs: tuple[str, ...] = ()
    observed_at: datetime = field(default_factory=utc_now)
    raw_result: Any = None

    @classmethod
    def from_observation(cls, intent_id, obs):
        return cls(str(uuid4()), obs.attempt_id, intent_id, dict(obs.target_at_execution),
                   dict(obs.effect_scope), obs.commit_knowledge, tuple(obs.evidence_refs), obs.observed_at, obs.raw_result)
