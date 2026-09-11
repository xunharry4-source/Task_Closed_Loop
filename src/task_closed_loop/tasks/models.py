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
    status: str = "open"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskCandidate:
    task_identity: str
    reality_id: str
    description: str
    reality_basis: str
    expected_reality_result: str
    metadata: dict[str, Any] = field(default_factory=dict)

    candidate_id: str = field(default_factory=lambda: str(uuid4()))
    work_relation: str = ""
    reality_basis_refs: tuple[str, ...] = ()
    identity_anchor_refs: tuple[str, ...] = ()
    required_capability_ids: tuple[str, ...] = ()

    def materialize(self) -> Task:
        metadata = dict(self.metadata)
        metadata.update(
            {
                "candidate_id": self.candidate_id,
                "work_relation": self.work_relation,
                "reality_basis_refs": list(self.reality_basis_refs),
                "identity_anchor_refs": list(self.identity_anchor_refs),
                "required_capability_ids": list(self.required_capability_ids),
            }
        )
        return Task(
            task_id=str(uuid4()),
            task_identity=self.task_identity,
            reality_id=self.reality_id,
            description=self.description,
            reality_basis=self.reality_basis,
            expected_reality_result=self.expected_reality_result,
            metadata=metadata,
        )
