from __future__ import annotations

from task_closed_loop.integration.models import (
    CapabilityDescriptor,
    ResourceSnapshot,
)
from task_closed_loop.integration.capability_semantics import (
    observable_capability_refs,
)
from task_closed_loop.reality.models import RealitySnapshot
from task_closed_loop.tasks.generation_models import StructuralFinding
from task_closed_loop.tasks.models import Task, TaskCandidate


def materialized_reality_refs(
    reality: RealitySnapshot,
    resources: list[ResourceSnapshot] | None = None,
) -> set[str]:
    """Return refs that already represent observed/materialized reality."""

    refs = (
        set(reality.current_facts)
        | set(reality.evidence_refs)
        | set(reality.effect_refs)
    )

    for resource in resources or []:
        refs.add(str(resource.resource_id))
        refs.add(str(resource.source_identity))

        # A task_outcome resource carries what an observation actually returned.
        # The concrete objects it reports (gmail:message:..., db:row:..., and the
        # evidence backing them) are observed reality, so a descendant Task that
        # grounds itself in them is *more* specific than one citing only the
        # outcome id. Without this the audit rejects exactly the well-grounded
        # children that Task Proliferation is supposed to produce.
        if str(resource.resource_type).strip() == "task_outcome" and isinstance(
            resource.payload, dict
        ):
            for key in ("subject_refs", "evidence_refs", "effect_refs"):
                for value in resource.payload.get(key) or ():
                    text = str(value).strip()
                    if text:
                        refs.add(text)

    reality_id = str(reality.reality_id).strip()
    if reality_id:
        refs.add(reality_id)

    return refs


_REF_QUALIFIERS = (
    "resource:",
    "reality:",
    "fact:",
    "evidence:",
    "effect:",
)

_REF_PATH_BOUNDARIES = (".", "[", "/", "#")


def unresolved_reality_refs(
    refs,
    available_refs: set[str],
) -> set[str]:
    """Return the refs that cannot be grounded in currently available reality.

    A model often cites reality more precisely than a bare identifier — for example
    `resource:orders_rows.payload.rows[3]` or `reality:<id>.current_gaps[2]`. Those
    are *more* grounded than the bare id, so an exact-match-only check would throw
    away a valid discovery. A ref therefore resolves when it names a known identity,
    optionally behind a `resource:`/`reality:` qualifier and followed by a sub-path.

    Refs that name something not present in reality are still unresolved: that is the
    hallucination guard and it must keep failing.
    """

    unresolved: set[str] = set()
    for raw in refs:
        text = str(raw).strip()
        if not text:
            continue
        if text in available_refs:
            continue

        body = text
        lowered = text.lower()
        for qualifier in _REF_QUALIFIERS:
            if lowered.startswith(qualifier):
                body = text[len(qualifier):]
                break

        if body in available_refs:
            continue

        # A known identity may itself contain dots or colons, so match on the longest
        # identity that the ref starts with, at a real path boundary.
        if any(
            body.startswith(known)
            and body[len(known) : len(known) + 1] in _REF_PATH_BOUNDARIES
            for known in available_refs
            if known
        ):
            continue

        unresolved.add(text)
    return unresolved


def current_reality_refs(
    reality: RealitySnapshot,
    resources: list[ResourceSnapshot] | None = None,
    capabilities: list[CapabilityDescriptor] | None = None,
) -> set[str]:
    """Return valid grounding refs for Task validation.

    Materialized refs represent facts already observed. Observable Capability refs are
    also accepted, but only as *sensor/probe basis*. CandidateStructuralAudit prevents
    ordinary business Tasks from treating a capability-only basis as if it were an
    already observed business fact.
    """

    refs = materialized_reality_refs(reality, resources)
    refs |= observable_capability_refs(
        capabilities or []
    )
    return refs


def candidate_identity_anchors(candidate: TaskCandidate) -> tuple[str, ...]:
    anchors = candidate.identity_anchor_refs or candidate.reality_basis_refs
    return tuple(sorted(str(x) for x in anchors))


class CandidateStructuralAudit:
    def review(
        self,
        resources: list[ResourceSnapshot],
        reality: RealitySnapshot,
        candidate: TaskCandidate,
        existing_tasks: list[Task],
        capabilities: list[CapabilityDescriptor],
        all_existing_tasks: list[Task] | None = None,
    ) -> list[StructuralFinding]:
        findings: list[StructuralFinding] = []

        if candidate.reality_id != reality.reality_id:
            findings.append(
                StructuralFinding(
                    code="reality_identity_mismatch",
                    candidate_id=candidate.candidate_id,
                    message="Candidate Reality Identity 与 Current Reality 不一致。",
                    evidence=(candidate.reality_id, reality.reality_id),
                )
            )

        available_refs = current_reality_refs(
            reality,
            resources,
            capabilities,
        )
        basis_refs = set(candidate.reality_basis_refs)
        missing_basis = unresolved_reality_refs(basis_refs, available_refs)
        if missing_basis:
            findings.append(
                StructuralFinding(
                    code="missing_current_reality_basis",
                    candidate_id=candidate.candidate_id,
                    message="Candidate 引用了当前 Resources / Reality 中不存在的现实依据。",
                    evidence=tuple(sorted(missing_basis)),
                )
            )

        # A readable/searchable capability proves only that the system can acquire
        # reality. It cannot by itself prove that a sender/file/record/event/problem
        # already exists. Capability-only grounding is reserved for the dedicated
        # Observation Acquisition parent Task.
        capability_basis = {
            ref
            for ref in basis_refs
            if str(ref).startswith("capability:")
        }
        materialized_basis = basis_refs - capability_basis
        if (
            capability_basis
            and not materialized_basis
            and candidate.origin_type != "observation_acquisition"
        ):
            findings.append(
                StructuralFinding(
                    code="capability_only_basis_requires_observation_parent",
                    candidate_id=candidate.candidate_id,
                    message=(
                        "普通 Task 不能把可观察 Capability 本身当成已发生的现实；"
                        "应先生成 Observation Acquisition 父任务取得真实结果，再由 Outcome 生成子任务。"
                    ),
                    evidence=tuple(sorted(capability_basis)),
                )
            )

        if candidate.origin_type == "task_proliferation":
            expected_outcome_refs = {
                f"task_outcome:{outcome_id}"
                for outcome_id in candidate.parent_outcome_ids
                if str(outcome_id).strip()
            }
            missing_outcome_basis = expected_outcome_refs - basis_refs
            if not expected_outcome_refs or missing_outcome_basis:
                findings.append(
                    StructuralFinding(
                        code="proliferation_missing_parent_outcome_basis",
                        candidate_id=candidate.candidate_id,
                        message=(
                            "Task 自增殖候选必须直接引用其 parent Outcome 的 "
                            "task_outcome:<outcome_id> 现实依据。"
                        ),
                        evidence=tuple(sorted(missing_outcome_basis or expected_outcome_refs)),
                    )
                )

            # An Outcome may expose several independent children over time, but the
            # same Outcome must not repeatedly recreate the same child after that
            # child has already completed/failed and left the effective set.
            candidate_parent_outcomes = tuple(sorted(str(x) for x in candidate.parent_outcome_ids))
            normalized_relation = " ".join(candidate.work_relation.lower().split())
            candidate_anchors = candidate_identity_anchors(candidate)
            for historical in all_existing_tasks or []:
                if str(historical.metadata.get("origin_type", "")) != "task_proliferation":
                    continue
                historical_parent_outcomes = tuple(
                    sorted(str(x) for x in historical.metadata.get("parent_outcome_ids", ()))
                )
                if historical_parent_outcomes != candidate_parent_outcomes:
                    continue
                historical_relation = " ".join(
                    str(historical.metadata.get("work_relation", "")).lower().split()
                )
                historical_anchors = tuple(
                    sorted(str(x) for x in historical.metadata.get("identity_anchor_refs", ()))
                )
                if (
                    historical.task_identity == candidate.task_identity
                    or (
                        normalized_relation
                        and normalized_relation == historical_relation
                        and candidate_anchors == historical_anchors
                    )
                ):
                    findings.append(
                        StructuralFinding(
                            code="historical_proliferation_duplicate",
                            candidate_id=candidate.candidate_id,
                            message=(
                                "同一 parent Outcome 已经生成过同一后代工作关系；"
                                "旧 Outcome 不能在后续周期重复增殖同一子 Task。"
                            ),
                            evidence=(historical.task_id,) + candidate_parent_outcomes,
                        )
                    )
                    break

        current_capabilities = {
            capability.capability_id
            for capability in capabilities
            if str(capability.availability).lower() == "available"
        }

        same_identity_tasks = [
            task
            for task in existing_tasks
            if task.task_identity == candidate.task_identity
        ]
        duplicate_is_effective = bool(same_identity_tasks)
        if candidate.origin_type == "observation_acquisition" and same_identity_tasks:
            # Observation identity is a dedicated namespace. Unrelated business Tasks
            # must not suppress perception, and an old observation parent that can no
            # longer execute with the current Capability set must not deadlock a
            # replacement parent for the same normalized surface.
            duplicate_is_effective = False
            for task in same_identity_tasks:
                if str(task.metadata.get("origin_type", "")) != "observation_acquisition":
                    continue
                required = tuple(
                    str(value).strip()
                    for value in (
                        task.metadata.get("required_capability_ids")
                        or task.metadata.get("observation_capability_ids")
                        or ()
                    )
                    if str(value).strip()
                )
                if not required or set(required).issubset(current_capabilities):
                    duplicate_is_effective = True
                    break

        if duplicate_is_effective:
            findings.append(
                StructuralFinding(
                    code="existing_task_duplicate",
                    candidate_id=candidate.candidate_id,
                    message="Candidate 与仍然有效且当前可执行的 Existing Task 使用相同 Task Identity。",
                    evidence=(candidate.task_identity,),
                )
            )

        # Cross-Observation duplicate guard: a new parent Outcome ID must not create
        # another active business Task for the same stable reality object and same
        # work relation merely because the event/seed identity changed.  This check is
        # deliberately anchor-based; text equality alone is unsafe because two
        # different messages/rows/files can require the same work wording.
        if candidate.origin_type != "observation_acquisition":
            normalized_relation = " ".join(candidate.work_relation.lower().split())
            anchors = candidate_identity_anchors(candidate)
            if normalized_relation and anchors:
                for task in existing_tasks:
                    if str(task.metadata.get("origin_type", "")) == "observation_acquisition":
                        continue
                    historical_relation = " ".join(
                        str(task.metadata.get("work_relation", "")).lower().split()
                    )
                    historical_anchors = tuple(
                        sorted(
                            str(value)
                            for value in task.metadata.get("identity_anchor_refs", ())
                            if str(value).strip()
                        )
                    )
                    if (
                        historical_relation == normalized_relation
                        and historical_anchors
                        and historical_anchors == anchors
                        and task.task_identity != candidate.task_identity
                    ):
                        findings.append(
                            StructuralFinding(
                                code="existing_work_relation_duplicate",
                                candidate_id=candidate.candidate_id,
                                message=(
                                    "新的 Outcome/Seed Identity 指向仍然有效的同一业务对象与同一工作关系；"
                                    "不得因重复 Observation 再派生一个并行 Task。"
                                ),
                                evidence=(task.task_id,) + anchors,
                            )
                        )
                        break

        missing_caps = (
            set(candidate.required_capability_ids)
            - current_capabilities
        )
        if missing_caps:
            findings.append(
                StructuralFinding(
                    code="required_capability_unavailable",
                    candidate_id=candidate.candidate_id,
                    message="Candidate 声明依赖的 Capability 当前不可用。",
                    evidence=tuple(sorted(missing_caps)),
                )
            )

        if not candidate.work_relation.strip():
            findings.append(
                StructuralFinding(
                    code="missing_work_relation",
                    candidate_id=candidate.candidate_id,
                    message="Candidate 缺少明确现实工作关系。",
                )
            )

        return findings


class CandidateSetStructuralAudit:
    def deduplicate(
        self,
        candidates: list[TaskCandidate],
    ) -> tuple[list[TaskCandidate], list[StructuralFinding]]:
        accepted: list[TaskCandidate] = []
        findings: list[StructuralFinding] = []

        seen_identity: dict[str, tuple[str, ...]] = {}
        seen_relation: set[tuple[str, str, tuple[str, ...]]] = set()

        for candidate in candidates:
            anchors = candidate_identity_anchors(candidate)
            normalized_relation = " ".join(
                candidate.work_relation.lower().split()
            )
            relation_key = (
                candidate.reality_id,
                normalized_relation,
                anchors,
            )

            previous_anchors = seen_identity.get(candidate.task_identity)
            if previous_anchors is not None:
                if previous_anchors == anchors:
                    findings.append(
                        StructuralFinding(
                            code="candidate_identity_duplicate",
                            candidate_id=candidate.candidate_id,
                            message="Candidate Set 中重复发现同一 Task Identity。",
                            evidence=(candidate.task_identity,) + anchors,
                        )
                    )
                else:
                    findings.append(
                        StructuralFinding(
                            code="candidate_identity_collision",
                            candidate_id=candidate.candidate_id,
                            message="同一 Task Identity 指向不同现实身份锚点。",
                            evidence=(candidate.task_identity,) + previous_anchors + anchors,
                        )
                    )
                continue

            if normalized_relation and relation_key in seen_relation:
                findings.append(
                    StructuralFinding(
                        code="candidate_work_relation_duplicate",
                        candidate_id=candidate.candidate_id,
                        message="Candidate Set 中重复发现同一现实对象上的同一工作关系。",
                        evidence=(candidate.work_relation,) + anchors,
                    )
                )
                continue

            accepted.append(candidate)
            seen_identity[candidate.task_identity] = anchors
            seen_relation.add(relation_key)

        return accepted, findings
