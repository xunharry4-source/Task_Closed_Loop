from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now():
    return datetime.now(timezone.utc)


@dataclass
class Task:
    task_id: str
    task_identity: str
    reality_id: str
    description: str
    reality_basis: str
    expected_reality_result: str
    user_value: str = ""
    execution_steps: tuple[str, ...] = ()
    status: str = "open"
    created_at: datetime = field(
        default_factory=utc_now
    )
    updated_at: datetime = field(
        default_factory=utc_now
    )
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def user_output(self) -> dict[str, Any]:
        return {
            "task": self.description,
            "user_value": self.user_value,
            "expected_result": (
                self.expected_reality_result
            ),
            "execution_steps": list(
                self.execution_steps
            ),
        }


@dataclass
class TaskCandidate:
    task_identity: str
    reality_id: str
    description: str
    reality_basis: str
    expected_reality_result: str
    user_value: str = ""
    execution_steps: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    candidate_id: str = field(
        default_factory=lambda: str(uuid4())
    )
    work_relation: str = ""
    reality_basis_refs: tuple[str, ...] = ()
    identity_anchor_refs: tuple[str, ...] = ()
    required_capability_ids: tuple[str, ...] = ()
    origin_type: str = "reality_discovery"
    source_discovery_ids: tuple[str, ...] = ()
    parent_task_ids: tuple[str, ...] = ()
    parent_outcome_ids: tuple[str, ...] = ()
    proliferation_reason: str = ""

    def materialize(self) -> Task:
        metadata = dict(self.metadata)
        metadata.update(
            {
                "candidate_id": (
                    self.candidate_id
                ),
                "work_relation": (
                    self.work_relation
                ),
                "reality_basis_refs": list(
                    self.reality_basis_refs
                ),
                "identity_anchor_refs": list(
                    self.identity_anchor_refs
                ),
                "required_capability_ids": list(
                    self.required_capability_ids
                ),
                "origin_type": self.origin_type,
                "source_discovery_ids": list(
                    self.source_discovery_ids
                ),
                "parent_task_ids": list(
                    self.parent_task_ids
                ),
                "parent_outcome_ids": list(
                    self.parent_outcome_ids
                ),
                "proliferation_reason": (
                    self.proliferation_reason
                ),
            }
        )

        return Task(
            task_id=str(uuid4()),
            task_identity=self.task_identity,
            reality_id=self.reality_id,
            description=self.description,
            reality_basis=self.reality_basis,
            expected_reality_result=(
                self.expected_reality_result
            ),
            user_value=self.user_value,
            execution_steps=tuple(
                self.execution_steps
            ),
            metadata=metadata,
        )
