from __future__ import annotations

from .models import (
    DiagnosticFinding,
    DiagnosticSnapshot,
    current_reality_refs,
    history_refs,
    candidate_basis_refs,
)


ROOT = "R1"


class R1Reviewer:
    root = ROOT

    def review(self, snapshot: DiagnosticSnapshot) -> list[DiagnosticFinding]:
        findings: list[DiagnosticFinding] = []

        current_refs = current_reality_refs(snapshot)
        historical_refs = history_refs(snapshot)
        effective_ids = {task.task_identity for task in snapshot.effective_existing_tasks}

        for candidate in snapshot.candidate_tasks:
            basis_refs = candidate_basis_refs(candidate)

            if basis_refs:
                basis_set = set(basis_refs)
                current_basis = basis_set & current_refs
                history_basis = basis_set & historical_refs
                unknown_basis = basis_set - current_refs - historical_refs

                if history_basis and not current_basis:
                    findings.append(
                        DiagnosticFinding(
                            root=ROOT,
                            code="history_only_task_basis",
                            severity="high",
                            subject=candidate.task_identity,
                            challenge="当前 Task 能否在不依赖历史目标惯性的情况下成立？",
                            evidence=tuple(sorted(history_basis)),
                            consequence="候选 Task 的现实依据只存在于 History。",
                        )
                    )

                if unknown_basis:
                    findings.append(
                        DiagnosticFinding(
                            root=ROOT,
                            code="unbound_task_basis",
                            severity="high",
                            subject=candidate.task_identity,
                            challenge="候选 Task 的现实依据能否在本轮 Reality 输入中找到？",
                            evidence=tuple(sorted(unknown_basis)),
                            consequence="候选依赖了当前输入与相关历史都未提供的引用。",
                        )
                    )

            if candidate.task_identity in effective_ids:
                findings.append(
                    DiagnosticFinding(
                        root=ROOT,
                        code="duplicate_existing_task_identity",
                        severity="high",
                        subject=candidate.task_identity,
                        challenge="这个候选是否只是重新发现了仍然有效的 Existing Task？",
                        evidence=(candidate.task_identity,),
                        consequence="Candidate 与 Effective Existing Task 使用同一 Task Identity。",
                    )
                )

            if candidate.reality_id != snapshot.reality.reality_id:
                findings.append(
                    DiagnosticFinding(
                        root=ROOT,
                        code="candidate_reality_scope_mismatch",
                        severity="high",
                        subject=candidate.task_identity,
                        challenge="这个候选是否仍然属于当前正在审查的 Reality？",
                        evidence=(candidate.reality_id, snapshot.reality.reality_id),
                        consequence="Candidate 绑定了不同 Reality。",
                    )
                )

        return findings


def inspect(snapshot: DiagnosticSnapshot):
    return R1Reviewer().review(snapshot)
