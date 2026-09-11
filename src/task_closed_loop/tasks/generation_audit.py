from __future__ import annotations

from task_closed_loop.integration.models import CapabilityDescriptor
from task_closed_loop.reality.models import RealitySnapshot
from task_closed_loop.tasks.generation_models import StructuralFinding
from task_closed_loop.tasks.models import Task, TaskCandidate


def current_reality_refs(reality: RealitySnapshot) -> set[str]:
    return (
        set(reality.current_facts)
        | set(reality.evidence_refs)
        | set(reality.effect_refs)
    )


def candidate_identity_anchors(candidate: TaskCandidate) -> tuple[str, ...]:
    anchors = candidate.identity_anchor_refs or candidate.reality_basis_refs
    return tuple(sorted(str(x) for x in anchors))


class CandidateStructuralAudit:
    def review(
        self,
        reality: RealitySnapshot,
        candidate: TaskCandidate,
        existing_tasks: list[Task],
        capabilities: list[CapabilityDescriptor],
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

        available_refs = current_reality_refs(reality)
        missing_basis = set(candidate.reality_basis_refs) - available_refs
        if missing_basis:
            findings.append(
                StructuralFinding(
                    code="missing_current_reality_basis",
                    candidate_id=candidate.candidate_id,
                    message="Candidate 引用了 Current Reality 中不存在的现实依据。",
                    evidence=tuple(sorted(missing_basis)),
                )
            )

        existing_ids = {task.task_identity for task in existing_tasks}
        if candidate.task_identity in existing_ids:
            findings.append(
                StructuralFinding(
                    code="existing_task_duplicate",
                    candidate_id=candidate.candidate_id,
                    message="Candidate 与仍然有效的 Existing Task 使用相同 Task Identity。",
                    evidence=(candidate.task_identity,),
                )
            )

        current_capabilities = {
            capability.capability_id
            for capability in capabilities
            if str(capability.availability).lower() == "available"
        }
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
