from __future__ import annotations

from task_closed_loop.integration.models import (
    CapabilityDescriptor,
    ResourceSnapshot,
)
from task_closed_loop.reality.models import RealitySnapshot
from task_closed_loop.tasks.generation_models import StructuralFinding
from task_closed_loop.tasks.models import Task, TaskCandidate
from task_closed_loop.tasks.references import (
    CAPABILITY,
    TASK_OUTCOME,
    ReferenceContext,
    format_problems,
    parse_reference,
    reference_key,
    reference_without_path,
)


def reference_context(
    reality: RealitySnapshot,
    resources: list[ResourceSnapshot] | None = None,
    capabilities: list[CapabilityDescriptor] | None = None,
    *,
    allow_capability: bool,
) -> ReferenceContext:
    """The single place that decides what a Stage 3-7 citation may point at.

    `allow_capability=False` is the discovery layer: only reality that has already been
    observed/materialized counts. Candidate and final Task audits also accept an
    observable Capability, but only as sensor/probe basis; CandidateStructuralAudit
    prevents ordinary business Tasks from treating capability-only basis as an
    already observed business fact.
    """

    return ReferenceContext.build(
        reality=reality,
        resources=resources or [],
        capabilities=capabilities or [],
        allow_capability=allow_capability,
    )


def candidate_identity_anchors(candidate: TaskCandidate) -> tuple[str, ...]:
    if candidate.identity_anchor_refs:
        return tuple(sorted(str(x) for x in candidate.identity_anchor_refs))
    # Basis refs may point into a field of an object; identity is the object itself.
    return tuple(sorted({reference_without_path(x) for x in candidate.reality_basis_refs}))


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

        references = reference_context(
            reality,
            resources,
            capabilities,
            allow_capability=True,
        )
        basis_refs = {str(ref).strip() for ref in candidate.reality_basis_refs}
        missing_basis = references.problems(basis_refs)
        if missing_basis:
            findings.append(
                StructuralFinding(
                    code="missing_current_reality_basis",
                    candidate_id=candidate.candidate_id,
                    message=(
                        "based_on_refs 中有无法在当前输入里找到的引用："
                        + format_problems(missing_basis)
                    ),
                    evidence=tuple(sorted(missing_basis)),
                )
            )
        elif not basis_refs:
            findings.append(
                StructuralFinding(
                    code="missing_current_reality_basis",
                    candidate_id=candidate.candidate_id,
                    message="Candidate 没有给出任何 based_on_refs。",
                )
            )

        if candidate.origin_type != "observation_acquisition":
            anchor_problems = {
                str(ref).strip(): reason
                for ref in candidate.identity_anchor_refs
                if (reason := references.check_anchor(ref)) is not None
            }
            if anchor_problems:
                findings.append(
                    StructuralFinding(
                        code="invalid_identity_anchor",
                        candidate_id=candidate.candidate_id,
                        message=(
                            "about_object_refs 中有不合规的对象引用："
                            + format_problems(anchor_problems)
                        ),
                        evidence=tuple(sorted(anchor_problems)),
                    )
                )

        # A readable/searchable capability proves only that the system can acquire
        # reality. It cannot by itself prove that a sender/file/record/event/problem
        # already exists. Capability-only grounding is reserved for the dedicated
        # Observation Acquisition parent Task.
        capability_basis = {
            ref
            for ref in basis_refs
            if parse_reference(ref).kind == CAPABILITY
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
            expected_outcome_keys = {
                (TASK_OUTCOME, str(outcome_id).strip())
                for outcome_id in candidate.parent_outcome_ids
                if str(outcome_id).strip()
            }
            cited_keys = {reference_key(ref) for ref in basis_refs}
            missing_outcome_basis = {
                f"{kind}:{identity}"
                for kind, identity in expected_outcome_keys - cited_keys
            }
            expected_outcome_refs = {
                f"{kind}:{identity}" for kind, identity in expected_outcome_keys
            }
            if not expected_outcome_refs or missing_outcome_basis:
                findings.append(
                    StructuralFinding(
                        code="proliferation_missing_parent_outcome_basis",
                        candidate_id=candidate.candidate_id,
                        message=(
                            "Task 自增殖候选的 based_on_refs 必须包含每个来源 Outcome 的 "
                            "task_outcome:<outcome_id>（可带 #字段路径）。"
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
