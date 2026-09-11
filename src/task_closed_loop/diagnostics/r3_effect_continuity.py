from __future__ import annotations

from .models import (
    DiagnosticFinding,
    DiagnosticSnapshot,
    normalize_scope,
    target_ref,
)


ROOT = "R3"

COMMITTED_STATES = {
    "committed",
    "confirmed_committed",
    "confirmed committed",
}
UNKNOWN_STATES = {
    "unknown",
    "commit_unknown",
    "unresolved",
}


class R3Reviewer:
    root = ROOT

    def review(self, snapshot: DiagnosticSnapshot) -> list[DiagnosticFinding]:
        findings: list[DiagnosticFinding] = []

        for action in snapshot.planned_actions:
            action_scope = set(action.scope_keys)

            for effect in snapshot.reality_input.external_effects:
                effect_target = target_ref(getattr(effect, "target_at_execution", None))
                if effect_target != action.target_ref:
                    continue

                effect_scope = normalize_scope(getattr(effect, "effect_scope", None))
                overlap = action_scope & effect_scope
                if not overlap:
                    continue

                state = str(getattr(effect, "commit_knowledge", "")).lower()

                if state in COMMITTED_STATES:
                    findings.append(
                        DiagnosticFinding(
                            root=ROOT,
                            code="planned_action_reenters_committed_effect",
                            severity="critical",
                            subject=action.action_id,
                            challenge="计划中的动作是否已经在现实中发生过？",
                            evidence=tuple(sorted(overlap)),
                            consequence="Planned Action 与已确认提交的 Effect Scope 重叠。",
                        )
                    )

                if state in UNKNOWN_STATES:
                    findings.append(
                        DiagnosticFinding(
                            root=ROOT,
                            code="planned_action_reenters_unknown_effect",
                            severity="critical",
                            subject=action.action_id,
                            challenge="原 Effect 尚未确认时，这个动作是否会造成重复外部执行？",
                            evidence=tuple(sorted(overlap)),
                            consequence="Planned Action 与 Commit Knowledge 未解析的 Effect Scope 重叠。",
                        )
                    )

        return findings


def inspect(snapshot: DiagnosticSnapshot):
    return R3Reviewer().review(snapshot)
