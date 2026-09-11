from __future__ import annotations

from .models import DiagnosticFinding, DiagnosticSnapshot, evidence_map, candidate_basis_refs


ROOT = "R2"


def _fingerprint(evidence) -> tuple:
    return (
        evidence.source_identity,
        evidence.revision_or_time_position,
        evidence.authority_or_currentness,
        evidence.availability,
        evidence.reality_relation,
        repr(evidence.payload),
    )


class R2Reviewer:
    root = ROOT

    def review(self, snapshot: DiagnosticSnapshot) -> list[DiagnosticFinding]:
        findings: list[DiagnosticFinding] = []
        grouped = evidence_map(snapshot)

        for evidence_id, records in grouped.items():
            fingerprints = {_fingerprint(record) for record in records}
            if len(fingerprints) > 1:
                findings.append(
                    DiagnosticFinding(
                        root=ROOT,
                        code="same_evidence_id_conflicting_observations",
                        severity="high",
                        subject=evidence_id,
                        challenge="同一个 Evidence Identity 是否被多个不一致观测同时定义？",
                        evidence=tuple(sorted(repr(fp) for fp in fingerprints)),
                        consequence="Evidence Identity 的当前内容存在互相冲突的记录。",
                    )
                )

        input_ids = set(grouped)
        phantom_refs = set(snapshot.reality.evidence_refs) - input_ids
        if phantom_refs:
            findings.append(
                DiagnosticFinding(
                    root=ROOT,
                    code="phantom_reality_evidence_ref",
                    severity="high",
                    subject=snapshot.reality.reality_id,
                    challenge="Reality 中引用的 Evidence 是否真的存在于本轮输入？",
                    evidence=tuple(sorted(phantom_refs)),
                    consequence="Current Reality 引用了未提供的 Evidence。",
                )
            )

        unavailable_ids = {
            evidence.evidence_id
            for evidence in snapshot.reality_input.evidence
            if str(evidence.availability or "").lower()
            in {"unavailable", "deleted", "missing", "revoked"}
        }

        for candidate in snapshot.candidate_tasks:
            basis_refs = set(candidate_basis_refs(candidate))
            unavailable_basis = basis_refs & unavailable_ids
            if unavailable_basis:
                findings.append(
                    DiagnosticFinding(
                        root=ROOT,
                        code="task_depends_on_unavailable_evidence",
                        severity="high",
                        subject=candidate.task_identity,
                        challenge="这个 Task 的当前依据是否仍然可用？",
                        evidence=tuple(sorted(unavailable_basis)),
                        consequence="候选直接依赖当前不可用的 Evidence。",
                    )
                )

        return findings


def inspect(snapshot: DiagnosticSnapshot):
    return R2Reviewer().review(snapshot)
