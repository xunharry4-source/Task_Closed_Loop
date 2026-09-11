from __future__ import annotations

from .models import DiagnosticFinding, DiagnosticSnapshot, target_ref


ROOT = "R4"


class R4Reviewer:
    root = ROOT

    def review(self, snapshot: DiagnosticSnapshot) -> list[DiagnosticFinding]:
        findings: list[DiagnosticFinding] = []

        current_capability_ids = {
            capability.capability_id
            for capability in snapshot.capabilities
            if str(capability.availability).lower() == "available"
        }

        for action in snapshot.planned_actions:
            context = action.execution_context

            missing_caps = (
                set(action.required_capability_ids)
                - current_capability_ids
            )
            if missing_caps:
                findings.append(
                    DiagnosticFinding(
                        root=ROOT,
                        code="missing_current_capability",
                        severity="critical",
                        subject=action.action_id,
                        challenge="这个 Planned Action 在当前 Capability Snapshot 下还能执行吗？",
                        evidence=tuple(sorted(missing_caps)),
                        consequence="动作依赖当前不可用的 Capability。",
                    )
                )

            if context is None:
                findings.append(
                    DiagnosticFinding(
                        root=ROOT,
                        code="missing_execution_context",
                        severity="high",
                        subject=action.action_id,
                        challenge="准备执行的动作是否拥有当前 Execution Context？",
                        consequence="Planned Action 没有绑定当前执行上下文。",
                    )
                )
                continue

            context_target = target_ref(context.current_target)
            if context_target != action.target_ref:
                findings.append(
                    DiagnosticFinding(
                        root=ROOT,
                        code="current_target_mismatch",
                        severity="critical",
                        subject=action.action_id,
                        challenge="当前 Execution Context 的 Target 是否仍然是这个动作准备作用的对象？",
                        evidence=(action.target_ref, context_target),
                        consequence="Planned Action 与 Current Target 不一致。",
                    )
                )

            if action.approval_required:
                approval = str(context.approval or "").lower()
                if approval not in {"approved", "granted", "authorized"}:
                    findings.append(
                        DiagnosticFinding(
                            root=ROOT,
                            code="approval_not_currently_resolved",
                            severity="critical",
                            subject=action.action_id,
                            challenge="需要授权的动作当前是否拥有可确认的 Approval？",
                            evidence=(str(context.approval),),
                            consequence="动作需要 Approval，但当前上下文没有可确认的有效授权。",
                        )
                    )

        return findings


def inspect(snapshot: DiagnosticSnapshot):
    return R4Reviewer().review(snapshot)
