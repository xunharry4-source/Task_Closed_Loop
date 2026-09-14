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
    task_id: str = ""
    # Stable reality-object identities observed/affected by this effect when known.
    subject_refs: tuple[str, ...] = ()

    @classmethod
    def from_observation(cls, intent_or_id, obs):
        intent_id = getattr(
            intent_or_id,
            "execution_intent_id",
            intent_or_id,
        )
        task_id = getattr(intent_or_id, "task_id", "")
        return cls(
            str(uuid4()),
            obs.attempt_id,
            str(intent_id),
            dict(obs.target_at_execution),
            dict(obs.effect_scope),
            obs.commit_knowledge,
            tuple(obs.evidence_refs),
            obs.observed_at,
            obs.raw_result,
            str(task_id or ""),
            tuple(getattr(obs, "subject_refs", ()) or ()),
        )
